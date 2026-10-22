#!/usr/bin/env python3
"""Varianti di velocità: thread, contesto, quantizzazione int8.

Ogni variante usa lo stesso input (stesse candele) e lo stesso seed, così la
differenza di mediana e bande rispetto al baseline misura l'effetto della variante,
non il rumore del campionamento.

Uso:
    python scripts/speed_variants.py --variant base --samples 10
    python scripts/speed_variants.py --variant threads --samples 10
    python scripts/speed_variants.py --variant ctx256 --samples 10
    python scripts/speed_variants.py --variant int8 --samples 10
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "third_party" / "kronos"))

from forecast_demo import load_candles, load_predictor  # noqa: E402
from kronos_ensemble import forecast_paths  # noqa: E402

VARIANTS = {
    "base": {"threads": None, "context": 512, "int8": False},
    "threads": {"threads": 6, "context": 512, "int8": False},
    "ctx256": {"threads": 6, "context": 256, "int8": False},
    "int8": {"threads": 6, "context": 512, "int8": True},
}


def peak_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=sorted(VARIANTS), required=True)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--tf", default="1h")
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--horizon", type=int, default=24)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    settings = VARIANTS[args.variant]

    if settings["threads"]:
        torch.set_num_threads(int(settings["threads"]))
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    context = int(settings["context"])
    candles = load_candles(args.symbol, args.tf, lookback=context)
    started = time.perf_counter()
    predictor = load_predictor()
    predictor.max_context = context
    if settings["int8"]:
        predictor.model = torch.quantization.quantize_dynamic(
            predictor.model, {torch.nn.Linear}, dtype=torch.qint8)
    load_seconds = time.perf_counter() - started

    step = pd.Timedelta(hours=1) if args.tf == "1h" else pd.Timedelta(hours=4)
    y_ts = pd.Series(pd.date_range(candles["open_time"].iloc[-1] + step,
                                   periods=args.horizon, freq=step))
    started = time.perf_counter()
    paths = forecast_paths(
        predictor,
        candles[["open", "high", "low", "close", "volume"]],
        candles["open_time"].reset_index(drop=True), y_ts,
        pred_len=args.horizon, T=1.0, top_p=0.9, sample_count=args.samples,
    )
    infer_seconds = time.perf_counter() - started

    closes = paths[:, :, 3]
    final = closes[:, -1]
    payload = {
        "variant": args.variant, "settings": settings, "symbol": args.symbol,
        "tf": args.tf, "context": context, "samples": args.samples, "seed": args.seed,
        "load_seconds": round(load_seconds, 2),
        "infer_seconds": round(infer_seconds, 2),
        "seconds_per_path": round(infer_seconds / args.samples, 3),
        "peak_rss_mb": round(peak_mb(), 1),
        "median_final": round(float(np.median(final)), 2),
        "p10_final": round(float(np.percentile(final, 10)), 2),
        "p90_final": round(float(np.percentile(final, 90)), 2),
        "last_price": float(candles["close"].iloc[-1]),
    }
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    np.savez(out / f"speed-{args.variant}.npz", paths=paths)
    (out / f"speed-{args.variant}.json").write_text(json.dumps(payload, indent=1),
                                                    encoding="utf-8")
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
