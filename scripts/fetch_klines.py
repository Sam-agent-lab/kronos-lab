#!/usr/bin/env python3
"""Scarica e aggiorna le candele pubbliche di Binance in Parquet.

Solo endpoint pubblici (/api/v3/klines), nessuna chiave, nessun permesso di trading.
Ogni coppia symbol/timeframe ha un file: data/<SYMBOL>_<TF>.parquet con le colonne
open_time (UTC), open, high, low, close, volume, close_time.

Uso:
    python scripts/fetch_klines.py                # aggiorna tutto (incrementale)
    python scripts/fetch_klines.py --full         # riscarica da zero
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BASE = "https://api.binance.com/api/v3/klines"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
TIMEFRAMES = {"1h": 60, "4h": 240}
SHORT_TFS = {"5m": 5, "15m": 15}
DEFAULT_MONTHS = 24
PAGE = 1000
COLUMNS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
           "quote_volume", "trades", "taker_base", "taker_quote", "ignore"]


def _get(symbol: str, interval: str, start_ms: int | None = None) -> list[list]:
    params = {"symbol": symbol, "interval": interval, "limit": PAGE}
    if start_ms is not None:
        params["startTime"] = start_ms
    for attempt in range(4):
        try:
            response = requests.get(BASE, params=params, timeout=20)
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # rete instabile: riprova con attesa crescente
            if attempt == 3:
                raise
            print(f"  retry {attempt + 1}: {exc}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return []


def download(symbol: str, interval: str, start_ms: int | None = None) -> pd.DataFrame:
    rows: list[list] = []
    # senza startTime Binance restituisce le ULTIME 1000 candele, non le prime:
    # per la storia completa si parte da 0
    cursor = 0 if start_ms is None else start_ms
    while True:
        batch = _get(symbol, interval, cursor)
        if not batch:
            break
        rows.extend(batch)
        cursor = batch[-1][0] + 1
        if len(batch) < PAGE:
            break
        time.sleep(0.15)  # peso endpoint: 1200 richieste/minuto
    frame = pd.DataFrame(rows, columns=COLUMNS)
    if frame.empty:
        return frame
    frame["open_time"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    frame["close_time"] = pd.to_datetime(frame["close_time"], unit="ms", utc=True)
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = frame[column].astype(float)
    return frame[["open_time", "open", "high", "low", "close", "volume", "close_time"]]


def _start_ms(months: int | None) -> int | None:
    """Finestra parziale: il timeframe corto non serve su 9 anni di storia."""
    if not months:
        return None
    return int((pd.Timestamp.now(tz="UTC") - pd.DateOffset(months=months)).timestamp() * 1000)


def update(symbol: str, interval: str, full: bool = False,
           months: int | None = None) -> dict:
    DATA.mkdir(exist_ok=True)
    path = DATA / f"{symbol}_{interval}.parquet"
    if path.exists() and not full:
        existing = pd.read_parquet(path)
        start = int(existing["open_time"].iloc[-1].timestamp() * 1000) + 1
        fresh = download(symbol, interval, start)
        if fresh.empty:
            return {"symbol": symbol, "tf": interval, "rows": len(existing), "added": 0}
        merged = (pd.concat([existing, fresh])
                    .drop_duplicates(subset="open_time")
                    .sort_values("open_time"))
        merged.to_parquet(path, index=False)
        return {"symbol": symbol, "tf": interval, "rows": len(merged),
                "added": len(merged) - len(existing)}
    fresh = download(symbol, interval, _start_ms(months))
    fresh.to_parquet(path, index=False)
    return {"symbol": symbol, "tf": interval, "rows": len(fresh), "added": len(fresh)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="riscarica da zero")
    parser.add_argument("--symbols", nargs="*", default=SYMBOLS)
    parser.add_argument("--tf", nargs="*", default=None,
                        help="timeframe da scaricare (default 1h 4h); 5m/15m usano --months")
    parser.add_argument("--months", type=int, default=DEFAULT_MONTHS,
                        help="finestra in mesi per i timeframe corti (default 24)")
    args = parser.parse_args(argv)
    report = []
    intervals = args.tf or list(TIMEFRAMES)
    for symbol in args.symbols:
        for interval in intervals:
            months = args.months if interval in SHORT_TFS else None
            row = update(symbol, interval, full=args.full, months=months)
            report.append(row)
            print(json.dumps(row), flush=True)
    (DATA / "update-report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
