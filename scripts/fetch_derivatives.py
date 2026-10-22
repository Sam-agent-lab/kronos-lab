#!/usr/bin/env python3
"""Scarica funding rate e open interest storici dagli endpoint PUBBLICI dei futures Binance.

Nessuna chiave, nessun permesso: `/fapi/v1/fundingRate` e `/futures/data/openInterestHist`
sono pubblici. Serve per le feature della Fase 7-lite (costo di finanziamento e variazione
dell'interesse aperto *prima* dell'ancora, mai dopo).

Uso:
    python scripts/fetch_derivatives.py                 # aggiorna tutto
    python scripts/fetch_derivatives.py --symbols BTCUSDT
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "deriv"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
FUNDING = "https://fapi.binance.com/fapi/v1/fundingRate"
OI = "https://fapi.binance.com/futures/data/openInterestHist"
DAYS = 420          # copre la finestra di test + margine per il warm-up delle feature


def _get(url: str, params: dict, attempts: int = 4) -> list[dict]:
    for attempt in range(attempts):
        try:
            response = requests.get(url, params=params, timeout=20)
            response.raise_for_status()
            return response.json()
        except Exception as exc:            # rete instabile o rate limit
            if attempt == attempts - 1:
                raise
            print(f"  retry {attempt + 1}: {exc}", flush=True)
            time.sleep(2 * (attempt + 1))
    return []


def funding(symbol: str, start_ms: int) -> pd.DataFrame:
    rows, cursor = [], start_ms
    while True:
        batch = _get(FUNDING, {"symbol": symbol, "startTime": cursor, "limit": 1000})
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 1000:
            break
        cursor = batch[-1]["fundingTime"] + 1
        time.sleep(0.2)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["funding_time"] = pd.to_datetime(frame["fundingTime"], unit="ms", utc=True)
    frame["funding_rate"] = frame["fundingRate"].astype(float)
    return frame[["funding_time", "funding_rate"]].drop_duplicates("funding_time")


def open_interest(symbol: str, start_ms: int) -> pd.DataFrame:
    # Binance conserva la storia dell'open interest solo per ~30 giorni: oltre, l'endpoint
    # risponde 400. Si parte dal più vecchio timestamp accettato e si dichiara la copertura.
    floor_ms = int((pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=29))
                   .timestamp() * 1000)
    rows, cursor = [], max(start_ms, floor_ms)
    while True:
        batch = _get(OI, {"symbol": symbol, "period": "1h", "limit": 500,
                          "startTime": cursor})
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 500:
            break
        cursor = batch[-1]["timestamp"] + 1
        time.sleep(0.25)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["open_time"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    frame["open_interest"] = frame["sumOpenInterest"].astype(float)
    frame["open_interest_value"] = frame["sumOpenInterestValue"].astype(float)
    return frame[["open_time", "open_interest", "open_interest_value"]].drop_duplicates("open_time")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", default=SYMBOLS)
    parser.add_argument("--days", type=int, default=DAYS)
    args = parser.parse_args(argv)

    OUT.mkdir(parents=True, exist_ok=True)
    start_ms = int((pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=args.days))
                   .timestamp() * 1000)
    report = []
    for symbol in args.symbols:
        fund = funding(symbol, start_ms)
        if not fund.empty:                      # scritto subito: se l'OI fallisce non si perde
            fund.to_parquet(OUT / f"{symbol}_funding.parquet", index=False)
        try:
            oi = open_interest(symbol, start_ms)
        except Exception as exc:
            print(json.dumps({"symbol": symbol, "oi_error": str(exc)[:120]}), flush=True)
            oi = pd.DataFrame()
        if not oi.empty:
            oi.to_parquet(OUT / f"{symbol}_oi_1h.parquet", index=False)
        row = {"symbol": symbol, "funding_rows": len(fund), "oi_rows": len(oi)}
        report.append(row)
        print(json.dumps(row), flush=True)
    (OUT / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
