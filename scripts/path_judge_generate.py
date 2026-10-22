#!/usr/bin/env python3
"""Genera i forecast del "path judge" salvando TUTTI i 30 path (Fase finale Kronos).

Differenze rispetto a `evaluate.py`:
- campionamento fisso, non casuale: 1h ogni 4 ore (00/04/08/12/16/20 UTC), 4h due volte al
  giorno (00/12 UTC);
- orizzonte sempre 24 ore di mercato (1h → 24 candele, 4h → 6);
- `top_p=1.0` e `T=1.0` (nessun troncamento);
- **tutti i path** salvati in shard `.npz` float32, con metadati in `.jsonl`;
- solo dati dal 2025-08-15 in poi;
- un processo per gruppo di serie, con checkpoint e ripresa (`state.json`).

Uso (dentro il pod):
    python scripts/path_judge_generate.py --series BTCUSDT:1h,ETHUSDT:1h --tag run1
    python scripts/path_judge_generate.py --series DOGEUSDT:4h --limit 20 --benchmark
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "third_party" / "kronos"))

DATA = ROOT / "data"
OUT = ROOT / "paths"
START = pd.Timestamp("2025-08-15", tz="UTC")
STEP = {"1h": 60, "4h": 240}
ANCHOR_HOURS = {"1h": [0, 4, 8, 12, 16, 20], "4h": [0, 12]}
HORIZON = {"1h": 24, "4h": 6}
CONTEXT = 512
SAMPLES = 30
TOP_P = 1.0
TEMPERATURE = 1.0
TOKENIZER = "NeoQuasar/Kronos-Tokenizer-base"
MODEL = "NeoQuasar/Kronos-small"
SHARD_SIZE = 50


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_frame(symbol: str, tf: str) -> pd.DataFrame:
    frame = pd.read_parquet(DATA / f"{symbol}_{tf}.parquet").sort_values("open_time")
    return frame.iloc[:-1].reset_index(drop=True)


def anchors_for(frame: pd.DataFrame, tf: str) -> list[pd.Timestamp]:
    step = pd.Timedelta(minutes=STEP[tf])
    last_realized = frame["open_time"].iloc[len(frame) - HORIZON[tf] - 1]
    times = frame["open_time"]
    anchors = []
    for hour in ANCHOR_HOURS[tf]:
        candidates = times[(times >= START) & (times <= last_realized)]
        anchors.extend(candidates[candidates.dt.hour == hour].tolist())
    return sorted(set(anchors))


def load_predictor(device: str):
    from model import Kronos, KronosPredictor, KronosTokenizer

    tokenizer = KronosTokenizer.from_pretrained(TOKENIZER)
    model = Kronos.from_pretrained(MODEL)
    predictor = KronosPredictor(model, tokenizer, device=device, max_context=CONTEXT)
    predictor.max_context = CONTEXT
    return predictor


def forecast(predictor, frame: pd.DataFrame, idx: int, tf: str) -> tuple[np.ndarray, dict]:
    from kronos_ensemble import forecast_paths

    horizon = HORIZON[tf]
    window = frame.iloc[idx - CONTEXT + 1: idx + 1].reset_index(drop=True)
    step = pd.Timedelta(minutes=STEP[tf])
    y_ts = pd.Series(pd.date_range(window["open_time"].iloc[-1] + step,
                                   periods=horizon, freq=step))
    started = time.perf_counter()
    paths = forecast_paths(
        predictor, window[["open", "high", "low", "close", "volume"]],
        window["open_time"].reset_index(drop=True), y_ts,
        pred_len=horizon, T=TEMPERATURE, top_p=TOP_P, sample_count=SAMPLES,
    )
    elapsed = time.perf_counter() - started

    closes = paths[:, :, 3].astype(np.float32)
    last = float(window["close"].iloc[-1])
    bands = {f"p{q}": np.percentile(closes, q, axis=0) for q in (10, 25, 50, 75, 90)}
    final = closes[:, -1]
    meta = {
        "anchor": pd.Timestamp(window["open_time"].iloc[-1]).isoformat(),
        "tf": tf, "horizon": horizon, "last_price": last,
        "samples": SAMPLES, "top_p": TOP_P, "T": TEMPERATURE,
        "prob_up": float((final > last).mean()),
        "prob_up_at": {str(h): float((closes[:, h - 1] > last).mean())
                       for h in sorted({1, max(1, horizon // 2), horizon})},
        "median_final": float(np.median(final)),
        "mean_final": float(np.mean(final)),
        "bands": {k: [float(x) for x in v] for k, v in bands.items()},
        "path_final": [float(x) for x in final],
        "seconds": round(elapsed, 2),
        "generated_at": now_utc(),
    }
    return closes, meta


def run_series(predictor, symbol: str, tf: str, limit: int = 0, benchmark: bool = False) -> int:
    series_dir = OUT / f"{symbol}_{tf}"
    series_dir.mkdir(parents=True, exist_ok=True)
    state_path = series_dir / "state.json"
    meta_path = series_dir / "meta.jsonl"

    state = json.loads(state_path.read_text()) if state_path.is_file() else {"done": 0,
                                                                             "shard": 0,
                                                                             "last_anchor": None}
    done_anchors: set[str] = set()
    if meta_path.is_file():
        with meta_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    done_anchors.add(json.loads(line)["anchor"])
                except json.JSONDecodeError:
                    continue

    frame = load_frame(symbol, tf)
    anchors = anchors_for(frame, tf)
    pending = [a for a in anchors if a.isoformat() not in done_anchors]
    print(json.dumps({"event": "series", "symbol": symbol, "tf": tf,
                      "anchors": len(anchors), "done": len(done_anchors),
                      "pending": len(pending), "at": now_utc()}), flush=True)

    index = {ts: i for i, ts in enumerate(frame["open_time"])}
    buffer_paths, buffer_meta, shard_errors = [], [], 0
    shard = int(state.get("shard", 0))
    started = time.monotonic()
    made = 0

    def flush() -> None:
        nonlocal buffer_paths, buffer_meta, shard
        if not buffer_paths:
            return
        shard_path = series_dir / f"paths_{shard:03d}.npz"
        np.savez_compressed(shard_path, paths=np.stack(buffer_paths))
        with meta_path.open("a", encoding="utf-8") as handle:
            for block in buffer_meta:
                handle.write(json.dumps(block) + "\n")
        state_path.write_text(json.dumps({"done": state["done"] + len(buffer_meta),
                                          "shard": shard + 1,
                                          "last_anchor": buffer_meta[-1]["anchor"],
                                          "updated_at": now_utc()}))
        state["done"] += len(buffer_meta)
        shard += 1
        buffer_paths, buffer_meta = [], []

    for anchor in pending:
        if limit and made >= limit:
            break
        idx = index.get(anchor)
        if idx is None or idx < CONTEXT - 1:
            continue
        attempts = 0
        while True:
            try:
                closes, meta = forecast(predictor, frame, idx, tf)
                break
            except Exception as exc:                     # 2 retry, poi si annota e si prosegue
                attempts += 1
                shard_errors += 1
                print(json.dumps({"event": "error", "symbol": symbol, "tf": tf,
                                  "anchor": anchor.isoformat(), "attempt": attempts,
                                  "error": str(exc)[:200]}), flush=True)
                if attempts >= 3:
                    traceback.print_exc()
                    flush()
                    return 3
                time.sleep(2)
        buffer_paths.append(closes)
        meta.update({"symbol": symbol})
        buffer_meta.append(meta)
        made += 1
        if len(buffer_paths) >= SHARD_SIZE:
            flush()
        if made % 10 == 0 or benchmark:
            elapsed = time.monotonic() - started
            print(json.dumps({"event": "progress", "symbol": symbol, "tf": tf, "made": made,
                              "pending": len(pending), "last_anchor": meta["anchor"],
                              "s": meta["seconds"], "avg_s": round(elapsed / made, 2),
                              "at": now_utc()}), flush=True)
    flush()
    elapsed = time.monotonic() - started
    print(json.dumps({"event": "series_done", "symbol": symbol, "tf": tf, "made": made,
                      "seconds": round(elapsed, 1),
                      "per_forecast_s": round(elapsed / max(made, 1), 2),
                      "errors": shard_errors, "at": now_utc()}), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--series", required=True,
                        help="lista SYMBOL:TF separata da virgole, es. BTCUSDT:1h,ETHUSDT:4h")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--tag", default="")
    args = parser.parse_args(argv)

    import torch

    if args.device == "cuda" and not torch.cuda.is_available():
        print(json.dumps({"event": "fallback_cpu"}), flush=True)
        args.device = "cpu"

    OUT.mkdir(parents=True, exist_ok=True)
    predictor = load_predictor(args.device)
    print(json.dumps({"event": "start", "device": args.device, "series": args.series,
                      "tag": args.tag, "models": MODEL, "at": now_utc()}), flush=True)
    for item in args.series.split(","):
        symbol, tf = item.split(":")
        code = run_series(predictor, symbol, tf, args.limit, args.benchmark)
        if code:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
