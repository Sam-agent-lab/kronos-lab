#!/usr/bin/env python3
"""Fase 3: valutazione onesta di Kronos su dati mai visti, con checkpoint e ripresa.

Per ogni serie (asset × timeframe) sceglie **un** momento al giorno, in modo casuale ma
riproducibile: `slot = H(seed, symbol, tf, data) % slot_giornalieri`. La stessa ora vale per
tutte le varianti, così Small/Base/Tiny vedono le stesse candele.

Ogni forecast completato viene scritto subito in `results/<variant>/<tf>_<symbol>.jsonl`
(append + fsync) e `state.json` ricorda l'ultimo giorno fatto: se il pod muore si riparte
da lì senza rifare nulla.

Uso:
    python scripts/evaluate.py --variant small512 --tfs 1h 4h --device cuda
    python scripts/evaluate.py --variant small512 --tfs 1h --limit 3 --device cpu
    python scripts/evaluate.py --variant small512 --benchmark-minutes 5 --device cuda
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "third_party" / "kronos"))

DATA = ROOT / "data"
RESULTS = ROOT / "results"

VARIANTS = {
    "small512": ("NeoQuasar/Kronos-small", 512),
    "base512": ("NeoQuasar/Kronos-base", 512),
    "small256": ("NeoQuasar/Kronos-small", 256),
}
TOKENIZER = "NeoQuasar/Kronos-Tokenizer-base"
STEP = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}          # minuti
HORIZON = {"5m": 12, "15m": 12, "1h": 24, "4h": 6}
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
SEED = 20261022
TEST_DAYS = 365
QUANTILES = (10, 25, 50, 75, 90)


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slot_of_day(symbol: str, tf: str, day: pd.Timestamp, slots: int) -> int:
    key = f"{SEED}|{symbol}|{tf}|{day.strftime('%Y-%m-%d')}"
    digest = hashlib.sha256(key.encode()).hexdigest()
    return int(digest[:8], 16) % slots


def load_frame(symbol: str, tf: str) -> pd.DataFrame:
    path = DATA / f"{symbol}_{tf}.parquet"
    frame = pd.read_parquet(path).sort_values("open_time").reset_index(drop=True)
    # solo candele chiuse: l'ultima barra aperta non è un dato disponibile
    return frame.iloc[:-1].reset_index(drop=True)


def load_predictor(model_name: str, context: int, device: str):
    from model import Kronos, KronosPredictor, KronosTokenizer

    tokenizer = KronosTokenizer.from_pretrained(TOKENIZER)
    model = Kronos.from_pretrained(model_name)
    predictor = KronosPredictor(model, tokenizer, device=device, max_context=context)
    predictor.max_context = context
    return predictor


def forecast_at(predictor, frame: pd.DataFrame, idx: int, tf: str, samples: int,
                context: int) -> dict:
    from kronos_ensemble import forecast_paths

    horizon = HORIZON[tf]
    window = frame.iloc[idx - context + 1: idx + 1].reset_index(drop=True)
    step = pd.Timedelta(minutes=STEP[tf])
    y_ts = pd.Series(pd.date_range(window["open_time"].iloc[-1] + step,
                                   periods=horizon, freq=step))
    started = time.perf_counter()
    paths = forecast_paths(
        predictor, window[["open", "high", "low", "close", "volume"]],
        window["open_time"].reset_index(drop=True), y_ts,
        pred_len=horizon, T=1.0, top_p=0.9, sample_count=samples,
    )
    elapsed = time.perf_counter() - started

    closes = paths[:, :, 3]
    last_price = float(window["close"].iloc[-1])
    bands = {f"p{q}": np.percentile(closes, q, axis=0) for q in QUANTILES}
    final = closes[:, -1]
    return {
        "anchor": pd.Timestamp(window["open_time"].iloc[-1]).isoformat(),
        "last_price": last_price,
        "horizon": horizon,
        "bands": {key: [float(v) for v in series] for key, series in bands.items()},
        "median_final": float(np.median(final)),
        "prob_up": float((final > last_price).mean()),
        "prob_up_at": {str(h): float((closes[:, h - 1] > last_price).mean())
                       for h in sorted({1, max(1, horizon // 2), horizon})},
        "path_final": [float(v) for v in final],
        "realized": [float(v) for v in
                     frame["close"].iloc[idx + 1: idx + 1 + horizon].to_numpy()],
        "seconds": round(elapsed, 2),
        "samples": samples,
        "generated_at": now_utc(),
    }


def read_done(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    done = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                done.add(json.loads(line)["anchor"])
            except (json.JSONDecodeError, KeyError):
                continue  # riga troncata da un kill: si rifà
    return done


def plan_days(frame: pd.DataFrame, context: int, days: int) -> list[pd.Timestamp]:
    """Giorni in cui esistono contesto sufficiente e esito già realizzato."""
    horizon = HORIZON_CURRENT
    first = frame["open_time"].iloc[context - 1]
    last = frame["open_time"].iloc[len(frame) - horizon - 1]
    start = max(first, (frame["open_time"].iloc[-1] - pd.Timedelta(days=days)).normalize())
    days = [d for d in pd.date_range(start.normalize(), last.normalize(), freq="D", tz="UTC")
            if first.normalize() <= d <= last.normalize()]
    # finestra canonica: esattamente TEST_DAYS giorni di calendario, uguale per OGNI serie e
    # per OGNI variante (altrimenti il bordo della finestra dà 365 o 366 giorni a seconda dei dati)
    return days[-TEST_DAYS:]


HORIZON_CURRENT = 24


def main(argv: list[str] | None = None) -> int:
    global HORIZON_CURRENT
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", default="small512", choices=sorted(VARIANTS))
    parser.add_argument("--tfs", nargs="*", default=["1h", "4h"])
    parser.add_argument("--symbols", nargs="*", default=SYMBOLS)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--days", type=int, default=TEST_DAYS)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--limit", type=int, default=0, help="max forecast per serie (debug)")
    parser.add_argument("--benchmark-minutes", type=float, default=0.0)
    parser.add_argument("--threads", type=int, default=6)
    args = parser.parse_args(argv)

    import torch

    if args.device == "cuda" and not torch.cuda.is_available():
        print("CUDA non disponibile: passo a CPU", flush=True)
        args.device = "cpu"
    if args.device == "cpu":
        torch.set_num_threads(args.threads)

    model_name, context = VARIANTS[args.variant]
    out_dir = RESULTS / args.variant
    out_dir.mkdir(parents=True, exist_ok=True)
    print(json.dumps({"event": "start", "variant": args.variant, "model": model_name,
                      "context": context, "device": args.device, "tfs": args.tfs,
                      "samples": args.samples, "at": now_utc()}), flush=True)
    predictor = load_predictor(model_name, context, args.device)

    deadline = (time.monotonic() + args.benchmark_minutes * 60
                if args.benchmark_minutes else None)
    total, started = 0, time.monotonic()

    for tf in args.tfs:
        HORIZON_CURRENT = HORIZON[tf]
        slots = 24 * 60 // STEP[tf]
        for symbol in args.symbols:
            frame = load_frame(symbol, tf)
            path = out_dir / f"{tf}_{symbol}.jsonl"
            state_path = out_dir / f"{tf}_{symbol}.state.json"
            done = read_done(path)
            days = plan_days(frame, context, args.days)
            print(json.dumps({"event": "series", "tf": tf, "symbol": symbol,
                              "days": len(days), "done": len(done), "at": now_utc()}),
                  flush=True)
            made = 0
            for day in days:
                if deadline and time.monotonic() > deadline:
                    break
                if args.limit and made >= args.limit:
                    break
                slot = slot_of_day(symbol, tf, day, slots)
                anchor_ts = day + pd.Timedelta(minutes=slot * STEP[tf])
                positions = frame.index[frame["open_time"] <= anchor_ts]
                if len(positions) == 0:
                    continue
                idx = int(positions[-1])
                if idx < context - 1 or idx + HORIZON[tf] >= len(frame):
                    continue
                anchor = pd.Timestamp(frame["open_time"].iloc[idx]).isoformat()
                if anchor in done:
                    continue
                record = forecast_at(predictor, frame, idx, tf, args.samples, context)
                record.update({"symbol": symbol, "tf": tf, "variant": args.variant,
                               "model": model_name, "context": context,
                               "slot": slot})
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                done.add(anchor)
                made += 1
                total += 1
                state_path.write_text(json.dumps(
                    {"last_anchor": anchor, "done": len(done), "updated_at": now_utc()}),
                    encoding="utf-8")
                elapsed = time.monotonic() - started
                print(json.dumps({"event": "forecast", "tf": tf, "symbol": symbol,
                                  "anchor": anchor, "n": total,
                                  "s": record["seconds"],
                                  "prob_up": round(record["prob_up"], 3),
                                  "avg_s": round(elapsed / max(total, 1), 2),
                                  "at": now_utc()}), flush=True)
            if deadline and time.monotonic() > deadline:
                break
        if deadline and time.monotonic() > deadline:
            break

    elapsed = time.monotonic() - started
    summary = {"event": "done", "variant": args.variant, "forecasts": total,
               "seconds": round(elapsed, 1),
               "per_forecast_s": round(elapsed / max(total, 1), 2), "at": now_utc()}
    print(json.dumps(summary), flush=True)
    (out_dir / "run-summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
