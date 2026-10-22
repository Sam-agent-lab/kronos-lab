#!/usr/bin/env python3
"""Fonti esterne gratuite per il "path judge": on-chain, stablecoin, indici macro.

Tutte gratuite e senza chiave:
- Coin Metrics **Community** — flussi di exchange (FlowInExUSD/FlowOutExUSD) e supply sugli
  exchange (SplyExNtv) per BTC ed ETH, giornalieri;
- DefiLlama — capitalizzazione totale delle stablecoin, giornaliera;
- Yahoo Finance — chiusure giornaliere di Nasdaq-100 (^NDX) e dollaro (DX-Y.NYB).

Le serie giornaliere vengono **ritardate di 2 giorni** in fase di costruzione delle feature:
il dato del giorno D è pubblicato con lag, usarlo lo stesso giorno sarebbe look-ahead.

Uso:
    python scripts/fetch_external.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "external"
START = "2025-07-01"          # un po' prima del periodo utile, per i ritardi
HEADERS = {"User-Agent": "Mozilla/5.0"}


def coinmetrics(asset: str, metrics: str) -> pd.DataFrame:
    url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    rows: list[dict] = []
    page = None
    while True:
        params = {"assets": asset, "metrics": metrics, "frequency": "1d",
                  "start_time": START, "page_size": 1000}
        if page:
            params["next_page_token"] = page
        response = requests.get(url, params=params, timeout=30, headers=HEADERS)
        response.raise_for_status()
        payload = response.json()
        rows.extend(payload.get("data", []))
        page = payload.get("next_page_token")
        if not page:
            break
        time.sleep(0.2)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["time"]).dt.tz_convert("UTC").dt.normalize()
    keep = ["date"] + [m for m in metrics.split(",") if m in frame.columns]
    return frame[keep].sort_values("date").reset_index(drop=True)


def defillama_stablecoins() -> pd.DataFrame:
    response = requests.get("https://stablecoins.llama.fi/stablecoincharts/all",
                            timeout=60, headers=HEADERS)
    response.raise_for_status()
    payload = response.json()
    rows = []
    for item in payload:
        try:
            stamp = pd.to_datetime(int(item["date"]), unit="s", utc=True).normalize()
            total = float(item["totalCirculating"]["peggedUSD"])
        except (KeyError, ValueError, TypeError):
            continue
        rows.append({"date": stamp, "stablecoin_usd": total})
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def yahoo(symbol: str, name: str) -> pd.DataFrame:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    response = requests.get(url, params={"range": "2y", "interval": "1d"},
                            timeout=30, headers=HEADERS)
    response.raise_for_status()
    result = response.json()["chart"]["result"][0]
    stamps = pd.to_datetime(result["timestamp"], unit="s", utc=True).normalize()
    closes = result["indicators"]["quote"][0]["close"]
    frame = pd.DataFrame({"date": stamps, name: closes}).dropna()
    return frame.sort_values("date").reset_index(drop=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report = {}

    onchain = coinmetrics("btc", "FlowInExUSD,FlowOutExUSD,SplyExNtv")
    if not onchain.empty:
        onchain.to_parquet(OUT / "btc_onchain.parquet", index=False)
        report["btc_onchain"] = {"rows": len(onchain), "from": str(onchain["date"].min())[:10]}
    time.sleep(1)
    eth = coinmetrics("eth", "FlowInExUSD,FlowOutExUSD")
    if not eth.empty:
        eth.to_parquet(OUT / "eth_onchain.parquet", index=False)
        report["eth_onchain"] = {"rows": len(eth), "from": str(eth["date"].min())[:10]}

    stable = defillama_stablecoins()
    stable.to_parquet(OUT / "stablecoins.parquet", index=False)
    report["stablecoins"] = {"rows": len(stable), "from": str(stable["date"].min())[:10]}

    ndx = yahoo("%5ENDX", "ndx")
    ndx.to_parquet(OUT / "ndx.parquet", index=False)
    report["ndx"] = {"rows": len(ndx), "from": str(ndx["date"].min())[:10]}

    dxy = yahoo("DX-Y.NYB", "dxy")
    dxy.to_parquet(OUT / "dxy.parquet", index=False)
    report["dxy"] = {"rows": len(dxy), "from": str(dxy["date"].min())[:10]}

    (OUT / "report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
