#!/usr/bin/env python3
"""Baseline naive per il path judge: "sempre short" e "regola di trend", stesso sizing.

Universo identico ai forecast: slot 4h alle 00 e 12 UTC dal 2025-08-15, orizzonte 24 ore
(6 candele), una posizione alla volta per asset. Il rendimento long di uno slot è
`close(anchor + 6 candele) / close(anchor) - 1`; short è il suo negativo.

Sizing identico al resto: 10 sleeve da 1/10, nessuna leva, nessun riuso di capitale.
Fee: maker 0,02%, taker 0,05%, spot 0,1% per lato.

Uso:
    python scripts/path_judge_baselines.py --period validation
    python scripts/path_judge_baselines.py --period lockbox     # solo dopo la review Opus
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "results" / "path_judge"
OP_REVIEW = ROOT / "docs" / "op-review-pathjudge.md"

ASSETS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
          "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "TRXUSDT"]
START = pd.Timestamp("2025-08-15", tz="UTC")
LOCKBOX_START = pd.Timestamp("2026-07-24", tz="UTC")
HORIZON = 6                      # 6 candele 4h = 24 ore
FEES = {"maker 0.02%": 0.0002, "taker 0.05%": 0.0005, "spot 0.1%": 0.001}


def slots(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    frame = pd.read_parquet(DATA / f"{symbol}_4h.parquet").sort_values("open_time")
    frame = frame.iloc[:-1].reset_index(drop=True)
    frame["ema50"] = frame["close"].ewm(span=50, adjust=False).mean()
    frame["ema200"] = frame["close"].ewm(span=200, adjust=False).mean()
    frame["exit_close"] = frame["close"].shift(-HORIZON)
    frame = frame[(frame["open_time"].dt.hour.isin([0, 12]))
                  & (frame["open_time"] >= start) & (frame["open_time"] <= end)]
    frame = frame.dropna(subset=["exit_close", "ema200"]).reset_index(drop=True)
    frame["long_ret"] = frame["exit_close"] / frame["close"] - 1
    frame["trend_down"] = frame["ema50"] < frame["ema200"]
    return frame[["open_time", "close", "long_ret", "trend_down"]]


def pick_non_overlapping(frame: pd.DataFrame) -> pd.DataFrame:
    """Una posizione alla volta: si salta lo slot successivo finché la precedente è aperta."""
    kept, open_until = [], None
    for _, row in frame.sort_values("open_time").iterrows():
        if open_until is not None and row["open_time"] < open_until:
            continue
        kept.append(row)
        open_until = row["open_time"] + pd.Timedelta(hours=24)
    return pd.DataFrame(kept)


def portfolio(per_asset: dict[str, pd.Series], fee: float) -> dict:
    """10 sleeve da 1/10: rendimento totale = media dei rendimenti composti delle sleeve."""
    returns = {}
    curves = []
    for symbol, gross in per_asset.items():
        net = gross - 2 * fee
        returns[symbol] = float((1 + net).prod() - 1)
        curves.append(net.groupby(net.index.floor("D")).sum().rename(symbol))
    curve = pd.concat(curves, axis=1).fillna(0.0).sum(axis=1) / len(ASSETS)
    equity = (1 + curve).cumprod()
    return {
        "total_return": float(np.mean(list(returns.values()))),
        "max_dd": float((equity / equity.cummax() - 1).min()) if len(equity) else 0.0,
        "sleeves_positive": int(sum(1 for v in returns.values() if v > 0)),
        "per_asset": {k: round(v, 4) for k, v in returns.items()},
    }


def evaluate(period_start: pd.Timestamp, period_end: pd.Timestamp) -> dict:
    strategies = {"Sempre short": {}, "Regola di trend": {}, "Buy & hold": {}}
    counts = {"Sempre short": 0, "Regola di trend": 0, "Buy & hold": 0}
    wins = {"Sempre short": 0, "Regola di trend": 0, "Buy & hold": 0}

    for symbol in ASSETS:
        frame = pick_non_overlapping(slots(symbol, period_start, period_end))
        if frame.empty:
            continue
        index = pd.DatetimeIndex(frame["open_time"])
        long_gross = pd.Series(frame["long_ret"].to_numpy(), index=index)
        short_gross = -long_gross
        trend_gross = pd.Series(np.where(frame["trend_down"].to_numpy(), -frame["long_ret"].to_numpy(),
                                        frame["long_ret"].to_numpy()), index=index)
        strategies["Sempre short"][symbol] = short_gross
        strategies["Regola di trend"][symbol] = trend_gross
        strategies["Buy & hold"][symbol] = long_gross
        for name, gross in (("Sempre short", short_gross),
                            ("Regola di trend", trend_gross),
                            ("Buy & hold", long_gross)):
            counts[name] += len(gross)
            wins[name] += int((gross - 2 * FEES["maker 0.02%"] > 0).sum())

    report = {"period_from": str(period_start)[:10], "period_to": str(period_end)[:10],
              "results": {}}
    for name, per_asset in strategies.items():
        if not per_asset:
            continue
        block = {"trades": counts[name],
                 "win_rate_maker": wins[name] / counts[name] if counts[name] else float("nan")}
        for fee_name, fee in FEES.items():
            block[fee_name] = portfolio(per_asset, fee)
        report["results"][name] = block
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", choices=["validation", "lockbox"], default="validation")
    args = parser.parse_args(argv)

    if args.period == "lockbox":
        if not OP_REVIEW.is_file():
            print(json.dumps({"error": "manca docs/op-review-pathjudge.md: lockbox sigillato"}))
            return 2
        start, end = LOCKBOX_START, pd.Timestamp.now(tz="UTC").normalize()
    else:
        start = START
        data_end = pd.read_parquet(DATA / "BTCUSDT_4h.parquet")["open_time"].max()
        end = LOCKBOX_START - pd.Timedelta(hours=4)
        del data_end

    report = evaluate(start, end)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"baselines_{args.period}.json"
    path.write_text(json.dumps(report, indent=1))

    lines = [f"Baseline naive — {args.period} ({report['period_from']} → {report['period_to']})",
             "| strategia | fee | trade | win rate | rendimento totale | max DD | sleeve positive |",
             "|---|---|---|---|---|---|---|"]
    for name, block in report["results"].items():
        for fee_name in FEES:
            part = block[fee_name]
            lines.append(f"| {name} | {fee_name} | {block['trades']} | "
                         f"{100 * block['win_rate_maker']:.1f}% | "
                         f"{100 * part['total_return']:+.2f}% | {100 * part['max_dd']:.1f}% | "
                         f"{part['sleeves_positive']}/10 |")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
