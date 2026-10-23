#!/usr/bin/env python3
"""Validazione con il sizing deciso per il lockbox: 10 sleeve da 1/10, senza leva.

Regola di capitale: capitale diviso in 10 parti uguali, una per asset. Ogni sleeve fa **una
posizione alla volta** (niente riuso del capitale mentre è impegnato) e non usa leva. Il
rendimento totale è la somma dei rendimenti delle 10 sleeve, ciascuno pesato 1/10.

"Return" nei criteri di successo = questo numero. Il rendimento per trade e il drawdown si
riportano ma non decidono.

Uso:
    python scripts/path_judge_sizing.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PRED = ROOT / "results" / "path_judge" / "validation_predictions.parquet"
DATA = ROOT / "data" / "path_judge_dataset.parquet"
OUT = ROOT / "results" / "path_judge" / "sizing.json"
STEP = {"1h": 60, "4h": 240}
FEES = {"maker 0.02%": 0.0002, "spot 0.1%": 0.001}
ASSETS = 10


def non_overlapping(frame: pd.DataFrame) -> pd.DataFrame:
    """Una posizione per asset alla volta, in ordine di tempo."""
    if frame.empty:
        return frame
    frame = frame.sort_values(["symbol", "anchor"]).reset_index(drop=True)
    keep = np.zeros(len(frame), dtype=bool)
    for _, index in frame.groupby("symbol", sort=False).indices.items():
        index = np.asarray(index)
        open_until = None
        for position in index:
            row = frame.iloc[position]
            anchor = pd.Timestamp(row["anchor"])
            if open_until is not None and anchor < open_until:
                continue
            keep[position] = True
            open_until = anchor + pd.Timedelta(minutes=STEP[row["tf"]] * int(row["horizon"]))
    return frame[keep]


def sleeve_return(frame: pd.DataFrame, fee: float) -> float:
    """Rendimento composto di una sleeve: (1+net) moltiplicati fra loro."""
    net = frame["gross_return"] - 2 * fee
    return float((1 + net).prod() - 1)


def portfolio(frame: pd.DataFrame, fee: float) -> dict:
    """Rendimento totale a capitale diviso in 10 sleeve + curva aggregata per drawdown."""
    per_asset = {}
    curves = []
    for symbol, group in frame.groupby("symbol"):
        per_asset[symbol] = sleeve_return(group, fee)
        net = (group["gross_return"] - 2 * fee)
        daily = (net.groupby(pd.to_datetime(group["anchor"]).dt.floor("D")).sum())
        curves.append(daily.rename(symbol))
    total = sum(per_asset.values()) / ASSETS
    # curva di portafoglio: ogni giorno si sommano i rendimenti delle sleeve attive / 10
    curve = pd.concat(curves, axis=1).fillna(0.0).sum(axis=1) / ASSETS
    equity = (1 + curve).cumprod()
    drawdown = float((equity / equity.cummax() - 1).min()) if len(equity) else 0.0
    return {
        "total_return": float(total),
        "equity_final": float(1 + total),
        "max_dd": drawdown,
        "assets_traded": len(per_asset),
        "sleeves_positive": int(sum(1 for value in per_asset.values() if value > 0)),
        "per_asset": {k: round(v, 5) for k, v in per_asset.items()},
    }


def summarise(frame: pd.DataFrame, fee: float) -> dict:
    n = len(frame)
    hits = int((frame["gross_return"] - 2 * fee > 0).sum()) if n else 0
    result = portfolio(frame, fee)
    result.update({
        "trades": n,
        "win_rate": hits / n if n else float("nan"),
        "mean_per_trade": float((frame["gross_return"] - 2 * fee).mean()) if n else float("nan"),
        "capital_utilisation": float(n * 6 / 4 / max(
            (pd.to_datetime(frame["anchor"]).max()
             - pd.to_datetime(frame["anchor"]).min()).days, 1) / ASSETS) if n else 0.0,
    })
    return result


def main() -> int:
    predictions = pd.read_parquet(PRED)
    dataset = pd.read_parquet(DATA)[["anchor", "symbol", "tf", "last_price", "realized_final",
                                     "gross_return", "is_lockbox"]]
    frame = predictions.merge(dataset, on=["anchor", "symbol", "tf"], how="left",
                              suffixes=("", "_ds"))

    models = {
        "Giudice A (soglia 0,70)": frame[frame["p_a"] >= 0.70],
        "Giudice B (soglia 0,60)": frame[frame["p_b"] >= 0.60],
        "Kronos senza filtro": frame,
    }
    report = {"models": {}, "buy_hold": {}}
    for name, subset in models.items():
        selected = non_overlapping(subset[["anchor", "symbol", "tf", "horizon",
                                           "gross_return"]])

        # il rendimento va ricalcolato dal dataset, non dal sottoinsieme filtrato
        keys = selected.set_index(["anchor", "symbol", "tf"]).index
        rows = frame.set_index(["anchor", "symbol", "tf"]).loc[keys].reset_index()
        report["models"][name] = {"trades": int(len(rows)),
                                  **{fee_name: summarise(rows, fee)
                                     for fee_name, fee in FEES.items()}}

    # buy & hold: per ogni asset, primo prezzo del periodo → ultimo esito realizzato
    hold_rows = []
    for symbol, group in dataset[~dataset["is_lockbox"]].groupby("symbol"):
        group = group.sort_values("anchor")
        entry = float(group["last_price"].iloc[0])
        exit_price = float(group["realized_final"].iloc[-1])
        hold_rows.append({"symbol": symbol, "anchor": group["anchor"].iloc[-1],
                          "tf": group["tf"].iloc[0], "gross_return": exit_price / entry - 1})
    hold = pd.DataFrame(hold_rows)
    report["buy_hold"] = {"trades": len(hold),
                          **{fee_name: summarise(hold, fee) for fee_name, fee in FEES.items()}}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1))

    lines = ["| modello | fee | trade | win rate | rendimento totale | per trade | max DD | sleeve positive |",
             "|---|---|---|---|---|---|---|---|"]
    for name in list(report["models"]) + ["Buy & hold (10 sleeve)"]:
        block = report["buy_hold"] if name.startswith("Buy") else report["models"][name]
        for fee_name in FEES:
            part = block[fee_name]
            lines.append(f"| {name} | {fee_name} | {part['trades']} | "
                         f"{100 * part['win_rate']:.1f}% | {100 * part['total_return']:+.2f}% | "
                         f"{100 * part['mean_per_trade']:+.3f}% | {100 * part['max_dd']:.1f}% | "
                         f"{part['sleeves_positive']}/10 |")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
