#!/usr/bin/env python3
"""Fase 1: forecast di prova con path reali + PNG con storia, path campionati e bande.

Usa ``kronos_ensemble.forecast_paths`` (non ``predict``) così ogni campione resta un
path separato: i percentili sono bande di previsione vere, non quantili di una media.

Uso:
    python scripts/forecast_demo.py --symbol BTCUSDT --tf 1h --samples 30 --horizon 24
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "third_party" / "kronos"))

LOOKBACK = 512


def load_candles(symbol: str, tf: str, lookback: int = LOOKBACK) -> pd.DataFrame:
    path = ROOT / "data" / f"{symbol}_{tf}.parquet"
    frame = pd.read_parquet(path).sort_values("open_time").reset_index(drop=True)
    # solo candele CHIUSE: l'ultima barra aperta non è un dato disponibile
    if len(frame) > 1:
        frame = frame.iloc[:-1]
    return frame.tail(lookback).reset_index(drop=True)


def load_predictor(model_name: str = "NeoQuasar/Kronos-small",
                   tokenizer_name: str = "NeoQuasar/Kronos-Tokenizer-base"):
    from model import Kronos, KronosPredictor, KronosTokenizer

    tokenizer = KronosTokenizer.from_pretrained(tokenizer_name)
    model = Kronos.from_pretrained(model_name)
    return KronosPredictor(model, tokenizer, device="cpu", max_context=LOOKBACK)


def run_forecast(predictor, candles: pd.DataFrame, tf: str, horizon: int,
                 samples: int) -> tuple[np.ndarray, pd.Series]:
    from kronos_ensemble import forecast_paths

    step = pd.Timedelta(hours=1) if tf == "1h" else pd.Timedelta(hours=4)
    y_ts = pd.Series(pd.date_range(candles["open_time"].iloc[-1] + step,
                                   periods=horizon, freq=step))
    paths = forecast_paths(
        predictor,
        candles[["open", "high", "low", "close", "volume"]],
        candles["open_time"].reset_index(drop=True),
        y_ts,
        pred_len=horizon, T=1.0, top_p=0.9, sample_count=samples,
    )
    return paths, y_ts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--tf", default="1h")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--horizon", type=int, default=24)
    parser.add_argument("--model", default="NeoQuasar/Kronos-small")
    args = parser.parse_args(argv)

    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    candles = load_candles(args.symbol, args.tf)
    if len(candles) < LOOKBACK:
        raise SystemExit(f"servono {LOOKBACK} candele, trovate {len(candles)}")

    started = time.perf_counter()
    predictor = load_predictor(args.model)
    load_seconds = time.perf_counter() - started

    cache = out / f"phase1_paths_{args.symbol}_{args.tf}_{args.samples}x{args.horizon}.npz"
    if cache.is_file():
        # riuso: l'inferenza CPU costa ~6 minuti, il disegno no
        stored = np.load(cache)
        paths = stored["paths"]
        y_ts = pd.Series(pd.to_datetime(stored["y_ts"]))
        infer_seconds = float(stored["infer_seconds"])
        print(f"[cache] path riusati da {cache.name}", flush=True)
    else:
        started = time.perf_counter()
        paths, y_ts = run_forecast(predictor, candles, args.tf, args.horizon, args.samples)
        infer_seconds = time.perf_counter() - started
        np.savez(cache, paths=paths, y_ts=y_ts.values, infer_seconds=float(infer_seconds))

    closes = paths[:, :, 3]                     # (samples, horizon)
    last_price = float(candles["close"].iloc[-1])
    bands = {f"p{q:02d}": np.percentile(closes, q, axis=0) for q in (10, 25, 50, 75, 90)}
    final = closes[:, -1]
    prob_up = float((final > last_price).mean())

    plot(args, candles, y_ts, closes, bands, last_price, out / "phase1_forecast.png")

    payload = {
        "symbol": args.symbol, "tf": args.tf, "model": args.model,
        "samples": args.samples, "horizon": args.horizon, "lookback": LOOKBACK,
        "load_seconds": round(load_seconds, 1),
        "infer_seconds": round(infer_seconds, 1),
        "last_price": last_price,
        "median_close_at_horizon": round(float(np.median(final)), 2),
        "median_return_pct": round((float(np.median(final)) / last_price - 1) * 100, 3),
        "prob_up": round(prob_up, 3),
        "band_width_pct_at_horizon": {
            "p10_p90": round(float((bands["p90"][-1] - bands["p10"][-1]) / last_price * 100), 3),
            "p25_p75": round(float((bands["p75"][-1] - bands["p25"][-1]) / last_price * 100), 3),
        },
        "paths_shape": list(paths.shape),
    }
    (out / "phase1_forecast.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(json.dumps(payload, indent=1))
    return 0


def plot(args, candles, y_ts, closes, bands, last_price, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax, zoom) = plt.subplots(2, 1, figsize=(12, 6.6), dpi=130,
                                   gridspec_kw={"height_ratios": [2.1, 1.0], "hspace": 0.35})
    history_x = candles["open_time"]
    ax.plot(history_x, candles["close"], color="#111827", linewidth=1.2,
            label=f"{args.symbol} {args.tf} chiusure (storia)")
    for index in range(min(10, closes.shape[0])):
        ax.plot(y_ts, closes[index], color="#3b82f6", linewidth=0.6, alpha=0.35)
    ax.plot(y_ts, bands["p50"], color="#1d4ed8", linewidth=1.6, label="mediana dei campioni")
    ax.fill_between(y_ts, bands["p10"], bands["p90"], color="#93c5fd", alpha=0.35,
                    label="banda 10–90%")
    ax.fill_between(y_ts, bands["p25"], bands["p75"], color="#1d4ed8", alpha=0.28,
                    label="banda 25–75%")
    ax.plot([y_ts.iloc[0], y_ts.iloc[-1]], [last_price, last_price],
            color="#6b7280", linestyle=":", linewidth=1,
            label=f"ultimo close {last_price:,.0f}")
    ax.set_title(f"Kronos-small · {args.symbol} {args.tf} · storia 512 candele · "
                 f"previsione {args.horizon} candele · {args.samples} path", fontsize=10.5)
    ax.set_ylabel("prezzo (USDT)")
    ax.grid(alpha=0.15)
    ax.legend(loc="upper right", fontsize=7.5, frameon=True, framealpha=0.85)
    # pannello sotto: zoom sulle sole 24 candele, così il fan non è schiacciato
    steps = range(len(y_ts))
    for index in range(min(10, closes.shape[0])):
        zoom.plot(steps, closes[index], color="#3b82f6", linewidth=0.7, alpha=0.45)
    zoom.plot(steps, bands["p50"], color="#1d4ed8", linewidth=1.6, label="mediana")
    zoom.fill_between(steps, bands["p10"], bands["p90"], color="#93c5fd", alpha=0.35,
                      label="10–90%")
    zoom.fill_between(steps, bands["p25"], bands["p75"], color="#1d4ed8", alpha=0.28,
                      label="25–75%")
    zoom.axhline(last_price, color="#6b7280", linestyle=":", linewidth=1)
    zoom.set_title("zoom sulle 24 candele previste", fontsize=9)
    zoom.set_xlabel("candele avanti")
    zoom.set_ylabel("USDT")
    zoom.legend(loc="upper left", fontsize=7, frameon=False)
    zoom.grid(alpha=0.15)

    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


if __name__ == "__main__":
    raise SystemExit(main())
