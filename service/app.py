"""FastAPI: serve l'ultimo forecast calcolato (locale, 127.0.0.1).

Il calcolo costa ~4 minuti su CPU: l'endpoint non ricalcola a ogni richiesta, serve
la cache prodotta dallo scheduler. `?refresh=1` forza il calcolo (uso manuale).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))
sys.path.insert(0, str(ROOT / "scripts"))

import core  # noqa: E402

app = FastAPI(title="Kronos forecast service", version="0.1.0")
CACHE = ROOT / "var" / "cache"


def _cached(symbol: str, tf: str) -> dict | None:
    path = CACHE / f"{symbol}_{tf}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/health")
def health() -> dict:
    cached = sorted(path.stem for path in CACHE.glob("*.json")) if CACHE.is_dir() else []
    return {"status": "ok", "cached_series": cached}


@app.get("/latest")
def latest_all() -> dict:
    rows = {}
    for symbol in core.SYMBOLS:
        for tf in core.TIMEFRAMES:
            payload = _cached(symbol, tf)
            if payload:
                rows[f"{symbol}_{tf}"] = {
                    key: payload[key] for key in
                    ("generated_at", "last_candle", "last_price", "median_final",
                     "prob_up", "regime", "bands_final", "band_width_pct", "samples")
                }
    return {"series": rows}


@app.get("/forecast")
def get_forecast(
    symbol: str = Query("BTCUSDT"),
    tf: str = Query("1h"),
    samples: int = Query(core.DEFAULT_SAMPLES, ge=1, le=100),
    horizon: int | None = Query(None, ge=1, le=48),
    refresh: bool = Query(False),
) -> dict:
    symbol = symbol.upper()
    if symbol not in core.SYMBOLS:
        raise HTTPException(404, f"asset non previsto: {symbol}")
    if tf not in core.TIMEFRAMES:
        raise HTTPException(404, f"timeframe non previsto: {tf}")
    if not refresh:
        payload = _cached(symbol, tf)
        if payload:
            return payload
    return core.forecast(symbol, tf, samples=samples, horizon=horizon)
