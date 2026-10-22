#!/usr/bin/env python3
"""Misura tempo e RAM di picco per un singolo forecast con N campioni.

Il picco RSS è per processo: per numeri puliti questo script fa UN solo run, e la
tabella si costruisce lanciandolo N volte (vedi `scripts/bench_table.sh`).

Uso: python scripts/bench_samples.py --samples 30
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "third_party" / "kronos"))

from forecast_demo import LOOKBACK, load_candles, load_predictor  # noqa: E402


def peak_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--tf", default="1h")
    parser.add_argument("--samples", type=int, required=True)
    parser.add_argument("--horizon", type=int, default=24)
    args = parser.parse_args(argv)

    baseline = peak_mb()
    candles = load_candles(args.symbol, args.tf)
    started = time.perf_counter()
    predictor = load_predictor()
    load_seconds = time.perf_counter() - started

    step = pd.Timedelta(hours=1) if args.tf == "1h" else pd.Timedelta(hours=4)
    y_ts = pd.Series(pd.date_range(candles["open_time"].iloc[-1] + step,
                                   periods=args.horizon, freq=step))
    started = time.perf_counter()
    predictor.predict(
        df=candles[["open", "high", "low", "close", "volume"]],
        x_timestamp=candles["open_time"].reset_index(drop=True), y_timestamp=y_ts,
        pred_len=args.horizon, T=1.0, top_p=0.9, sample_count=args.samples,
    )
    infer_seconds = time.perf_counter() - started

    print(json.dumps({
        "samples": args.samples,
        "horizon": args.horizon,
        "load_seconds": round(load_seconds, 2),
        "infer_seconds": round(infer_seconds, 2),
        "per_sample_seconds": round(infer_seconds / args.samples, 3),
        "peak_rss_mb": round(peak_mb(), 1),
        "peak_after_load_mb": round(baseline, 1),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
