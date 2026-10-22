#!/usr/bin/env python3
"""Backtest dei forecast salvati da evaluate.py: direzione, calibrazione, fee.

Legge `results/<variant>/<tf>_<symbol>.jsonl` e le candele in `data/`, e produce:
- hit rate direzionale della mediana a 1, metà e fine orizzonte;
- copertura delle bande 50% e 80% (calibrazione);
- pinball loss per quantile e MAE della mediana;
- strategia paper long/short/flat con due scenari di fee;
- confronto con buy-and-hold, sempre long e momentum.

Uso:
    python scripts/backtest.py --variant small512
    python scripts/backtest.py --variant small512 --tfs 1h 4h --format markdown
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESULTS = ROOT / "results"

LONG, SHORT = 0.60, 0.40           # soglie fissate PRIMA, nessun tuning sul test
FEE_SCENARIOS = {
    "no_fee": 0.0,                  # solo per misurare il modello, non è un caso reale
    "spot_0.1%": 0.001,             # Bybit EU spot, per lato
    "futures_taker_0.05%": 0.0005,  # futures, per lato
    "futures_maker_0.02%": 0.0002,  # futures, per lato
}
QUANTILES = (10, 25, 50, 75, 90)


def load_records(variant: str, tfs: list[str] | None = None) -> list[dict]:
    records: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for path in sorted((RESULTS / variant).glob("*.jsonl")):
        tf = path.name.split("_")[0]
        if tfs and tf not in tfs:
            continue
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = (record.get("symbol", ""), record.get("tf", ""), record.get("anchor", ""))
                if key in seen:                 # pull ripetuti non gonfiano il campione
                    continue
                if len(record.get("realized", [])) == record.get("horizon"):
                    seen.add(key)
                    records.append(record)
    return records


def pinball(quantile: float, actual: float, predicted: float) -> float:
    delta = actual - predicted
    return max(quantile * delta, (quantile - 1) * delta)


def score(records: list[dict]) -> dict:
    by_series: dict[tuple[str, str], list[dict]] = {}
    for record in records:
        by_series.setdefault((record["symbol"], record["tf"]), []).append(record)

    rows = []
    for (symbol, tf), items in sorted(by_series.items()):
        for record in items:
            last = record["last_price"]
            realized = np.asarray(record["realized"], dtype=float)
            horizon = record["horizon"]
            bands = {int(key[1:]): np.asarray(value, dtype=float)
                     for key, value in record["bands"].items()}
            middle = max(1, horizon // 2)
            row = {
                "symbol": symbol, "tf": tf, "anchor": record["anchor"],
                "prob_up": record["prob_up"], "last": last,
                "median_final": record["median_final"],
                "realized_final": float(realized[-1]),
                "hit_1": int(np.sign(bands[50][0] - last) == np.sign(realized[0] - last)),
                "hit_mid": int(np.sign(bands[50][middle - 1] - last)
                               == np.sign(realized[middle - 1] - last)),
                "hit_final": int(np.sign(bands[50][-1] - last)
                                 == np.sign(realized[-1] - last)),
                "in50": int(bands[25][-1] <= realized[-1] <= bands[75][-1]),
                "in80": int(bands[10][-1] <= realized[-1] <= bands[90][-1]),
                "mae": abs(bands[50][-1] - realized[-1]) / last,
                "pinball": float(np.mean([pinball(q / 100, realized[-1], bands[int(q)][-1])
                                          for q in QUANTILES])),
            }
            position = 1 if record["prob_up"] >= LONG else -1 if record["prob_up"] <= SHORT else 0
            row["position"] = position
            row["raw_return"] = position * (realized[-1] / last - 1)
            rows.append(row)

    frame = pd.DataFrame(rows)
    if frame.empty:
        return {"n": 0}

    dates = frame["anchor"].str[:10]
    summary: dict = {
        "n": int(len(frame)),
        "series": int(frame[["symbol", "tf"]].drop_duplicates().shape[0]),
        "hit_1": float(frame["hit_1"].mean()),
        "hit_mid": float(frame["hit_mid"].mean()),
        "hit_final": float(frame["hit_final"].mean()),
        "coverage_50": float(frame["in50"].mean()),
        "coverage_80": float(frame["in80"].mean()),
        "mae_pct": float(frame["mae"].mean() * 100),
        "pinball": float(frame["pinball"].mean()),
        "trades": int((frame["position"] != 0).sum()),
        "signal_share": float((frame["position"] != 0).mean()),
    }
    def equity_stats(net: pd.Series, dates: pd.Series) -> tuple[float, float]:
        # conto unico: ogni giorno pesa uguale (media dei net di quel giorno), poi si compone.
        # Comporre i singoli trade gonfierebbe/affonderebbe il risultato, perché 20 serie
        # possono aprire posizioni nello stesso giorno.
        daily = net.groupby(dates).mean()
        equity = (1 + daily).cumprod()
        peak = equity.cummax()
        drawdown = float((equity / peak - 1).min()) if len(equity) else 0.0
        return float(equity.iloc[-1]) if len(equity) else 1.0, drawdown

    for name, fee in FEE_SCENARIOS.items():
        cost = frame["position"].abs() * fee * 2      # entrata + uscita
        net = frame["raw_return"] - cost
        equity, drawdown = equity_stats(net, dates)
        summary[f"return_{name}"] = float(net.sum())
        summary[f"equity_{name}"] = equity
        summary[f"drawdown_{name}"] = drawdown
        summary[f"mean_trade_{name}"] = float(net[frame["position"] != 0].mean()) \
            if (frame["position"] != 0).any() else 0.0
        summary[f"win_rate_{name}"] = float((net[frame["position"] != 0] > 0).mean()) \
            if (frame["position"] != 0).any() else 0.0
    # posizione 1 su tutto l'orizzonte = buy and hold sullo stesso campione
    buy_hold = (frame["realized_final"] / frame["last"] - 1)
    summary["buy_hold_equity"] = float((1 + buy_hold.groupby(dates).mean()).cumprod().iloc[-1])
    summary["buy_hold_return"] = float(buy_hold.sum())
    summary["always_long_return_spot"] = float((buy_hold - 2 * FEE_SCENARIOS["spot_0.1%"]).sum())
    summary["per_tf"] = {}
    for tf, group in frame.groupby("tf"):
        net = group["raw_return"] - group["position"].abs() * 2 * FEE_SCENARIOS["spot_0.1%"]
        equity, drawdown = equity_stats(net, dates)
        summary["per_tf"][tf] = {
            "n": int(len(group)),
            "hit_final": float(group["hit_final"].mean()),
            "coverage_80": float(group["in80"].mean()),
            "equity_spot": equity,
            "drawdown_spot": drawdown,
            "mean_trade_spot": float(net[group["position"] != 0].mean())
            if (group["position"] != 0).any() else 0.0,
        }
    return summary


def to_markdown(summary: dict) -> str:
    if not summary.get("n"):
        return "nessun record completo"
    lines = [
        f"## Risultati ({summary['n']} forecast, {summary['series']} serie)",
        "",
        f"- Direzione mediana: 1 candela **{summary['hit_1']:.1%}**, "
        f"metà **{summary['hit_mid']:.1%}**, fine **{summary['hit_final']:.1%}** (50% = lancio di moneta)",
        f"- Calibrazione: dentro la banda 50% **{summary['coverage_50']:.1%}** (atteso 50%), "
        f"dentro la 80% **{summary['coverage_80']:.1%}** (atteso 80%)",
        f"- MAE mediana **{summary['mae_pct']:.2f}%**, pinball medio **{summary['pinball']:.4f}**",
        f"- Segnali: **{summary['trades']}** trade su {summary['n']} "
        f"({summary['signal_share']:.1%}), win rate spot {summary.get('win_rate_spot_0.1%', 0):.1%}",
        "",
        "| scenario fee | ritorno cumulato | media per trade |",
        "|---|---|---|",
    ]
    for name in FEE_SCENARIOS:
        lines.append(f"| {name} | {summary[f'return_{name}']:+.2%} | "
                     f"{summary[f'mean_trade_{name}']:+.4%} |")
    lines += [
        f"| buy & hold (stesso campione) | {summary['buy_hold_return']:+.2%} | — |",
        "",
        "| timeframe | n | direzione | copertura 80% | equity spot | max DD | media/trade |",
        "|---|---|---|---|---|---|---|",
    ]
    for tf, block in summary["per_tf"].items():
        lines.append(f"| {tf} | {block['n']} | {block['hit_final']:.1%} | "
                     f"{block['coverage_80']:.1%} | {block['equity_spot']:.2f}x | "
                     f"{block['drawdown_spot']:.1%} | {block['mean_trade_spot']:+.3%} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", default="small512")
    parser.add_argument("--tfs", nargs="*", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    records = load_records(args.variant, args.tfs)
    summary = score(records)
    summary["variant"] = args.variant
    text = to_markdown(summary)
    print(text)
    out = Path(args.out) if args.out else RESULTS / args.variant / "backtest.json"
    out.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"\nscritto {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
