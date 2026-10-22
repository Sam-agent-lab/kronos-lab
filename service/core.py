"""Nucleo del servizio: un forecast Kronos con path veri, bande e regime.

Un solo posto dove vivono i parametri di default (20 path), i thread e la regola
del regime, così servizio, scheduler e digest dicono sempre la stessa cosa.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "third_party" / "kronos"))

DEFAULT_SAMPLES = 20
HORIZON_BY_TF = {"1h": 24, "4h": 6}
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
TIMEFRAMES = ["1h", "4h"]
TREND_THRESHOLD = 0.70      # ≥70% dei path dallo stesso lato = regime direzionale
MODEL_NAME = "NeoQuasar/Kronos-small"
CONTEXT = 512

_PREDICTOR = None


def predictor():
    global _PREDICTOR
    if _PREDICTOR is None:
        from forecast_demo import load_predictor

        torch.set_num_threads(6)
        _PREDICTOR = load_predictor(MODEL_NAME)
        _PREDICTOR.max_context = CONTEXT
    return _PREDICTOR


def load_closed(symbol: str, tf: str, lookback: int = CONTEXT) -> pd.DataFrame:
    from forecast_demo import load_candles

    return load_candles(symbol, tf, lookback=lookback)


def regime_of(prob_up: float, threshold: float = TREND_THRESHOLD) -> str:
    if prob_up >= threshold:
        return "TRENDING_UP"
    if prob_up <= 1 - threshold:
        return "TRENDING_DOWN"
    return "CHOPPY"


def forecast(symbol: str, tf: str, samples: int = DEFAULT_SAMPLES,
             horizon: int | None = None) -> dict:
    from kronos_ensemble import forecast_paths

    horizon = horizon or HORIZON_BY_TF.get(tf, 24)
    candles = load_closed(symbol, tf)
    step = pd.Timedelta(hours=1) if tf == "1h" else pd.Timedelta(hours=4)
    y_ts = pd.Series(pd.date_range(candles["open_time"].iloc[-1] + step,
                                   periods=horizon, freq=step))
    started = time.perf_counter()
    paths = forecast_paths(
        predictor(), candles[["open", "high", "low", "close", "volume"]],
        candles["open_time"].reset_index(drop=True), y_ts,
        pred_len=horizon, T=1.0, top_p=0.9, sample_count=samples,
    )
    elapsed = time.perf_counter() - started

    closes = paths[:, :, 3]
    last_price = float(candles["close"].iloc[-1])
    last_candle = pd.Timestamp(candles["open_time"].iloc[-1]).isoformat()
    bands = {f"p{q}": np.percentile(closes, q, axis=0) for q in (10, 25, 50, 75, 90)}
    final = closes[:, -1]
    prob_up = float((final > last_price).mean())

    return {
        "symbol": symbol, "tf": tf, "model": MODEL_NAME, "samples": samples,
        "horizon": horizon, "context": CONTEXT,
        "last_price": last_price, "last_candle": last_candle,
        "median_final": float(np.median(final)),
        "prob_up": round(prob_up, 4),
        "regime": regime_of(prob_up),
        "bands_final": {key: round(float(value[-1]), 2) for key, value in bands.items()},
        "band_width_pct": {
            "p10_p90": round(float((bands["p90"][-1] - bands["p10"][-1]) / last_price * 100), 3),
            "p25_p75": round(float((bands["p75"][-1] - bands["p25"][-1]) / last_price * 100), 3),
        },
        "timestamps": [pd.Timestamp(value).isoformat() for value in y_ts],
        "bands": {key: [round(float(v), 2) for v in series] for key, series in bands.items()},
        "paths": [[round(float(v), 2) for v in path] for path in closes[:10]],
        "seconds": round(elapsed, 1),
        "generated_at": pd.Timestamp.utcnow().isoformat(),
    }
