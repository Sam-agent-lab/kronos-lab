#!/usr/bin/env python3
"""Backtest dei forecast salvati da evaluate.py: direzione, calibrazione, fee.

Correzioni dopo la review:
- **posizioni non sovrapposte per serie**: finché una posizione è aperta non se ne apre
  un'altra. Prima ogni giorno apriva una posizione anche sopra quella precedente, e la somma
  dei ritorni contava lo stesso movimento più volte.
- **buy & hold vero**: per ogni serie si compra al primo prezzo del periodo e si vende
  all'ultimo prezzo realizzato, senza fee e senza segnali. Prima era la somma di 365 ritorni.
- **pinball normalizzato** sul prezzo: prima era in unità di prezzo, non sommabile fra BTC e XRP.
- etichetta **"somma dei ritorni"** invece di "ritorno cumulato": sono somme di ritorni
  aritmetici, non un rendimento composto.

Uso:
    python scripts/backtest.py --variant small512
    python scripts/backtest.py --variant small512 --tfs 1h 4h
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

LONG, SHORT = 0.60, 0.40           # soglie fissate PRIMA, nessun tuning sul test
FEE_SCENARIOS = {
    "no_fee": 0.0,                  # solo per misurare il modello, non è un caso reale
    "spot_0.1%": 0.001,             # Bybit EU spot, per lato
    "futures_taker_0.05%": 0.0005,  # futures, per lato
    "futures_maker_0.02%": 0.0002,  # futures, per lato
}
QUANTILES = (10, 25, 50, 75, 90)
STEP = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}   # minuti per candela


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


def build_rows(records: list[dict]) -> pd.DataFrame:
    """Una riga per forecast, con segnale e posizione non sovrapposta dentro la serie."""
    by_series: dict[tuple[str, str], list[dict]] = {}
    for record in records:
        by_series.setdefault((record["symbol"], record["tf"]), []).append(record)

    rows = []
    for (symbol, tf), items in sorted(by_series.items()):
        open_until: pd.Timestamp | None = None
        for record in sorted(items, key=lambda item: item["anchor"]):
            anchor = pd.Timestamp(record["anchor"])
            horizon = record["horizon"]
            step = pd.Timedelta(minutes=STEP[tf])
            last = record["last_price"]
            realized = np.asarray(record["realized"], dtype=float)
            bands = {int(key[1:]): np.asarray(value, dtype=float)
                     for key, value in record["bands"].items()}
            middle = max(1, horizon // 2)

            signal = 1 if record["prob_up"] >= LONG else -1 if record["prob_up"] <= SHORT else 0
            blocked = open_until is not None and anchor < open_until
            position = 0 if blocked else signal
            if position != 0:
                open_until = anchor + step * horizon

            rows.append({
                "symbol": symbol, "tf": tf, "anchor": record["anchor"],
                "date": record["anchor"][:10],
                "prob_up": record["prob_up"], "last": last,
                "realized_final": float(realized[-1]),
                "signal": signal, "position": position, "blocked": bool(blocked),
                "hit_1": int(np.sign(bands[50][0] - last) == np.sign(realized[0] - last)),
                "hit_mid": int(np.sign(bands[50][middle - 1] - last)
                               == np.sign(realized[middle - 1] - last)),
                "hit_final": int(np.sign(bands[50][-1] - last) == np.sign(realized[-1] - last)),
                "in50": int(bands[25][-1] <= realized[-1] <= bands[75][-1]),
                "in80": int(bands[10][-1] <= realized[-1] <= bands[90][-1]),
                "mae": abs(bands[50][-1] - realized[-1]) / last,
                "pinball": float(np.mean([pinball(q / 100, realized[-1], bands[int(q)][-1])
                                          for q in QUANTILES])) / last,
                "raw_return": position * (realized[-1] / last - 1),
            })
    return pd.DataFrame(rows)


def equity_stats(net: pd.Series, dates: pd.Series) -> tuple[float, float]:
    """Un conto solo: ogni giorno pesa uguale, poi si compone."""
    daily = net.groupby(dates).mean()
    equity = (1 + daily).cumprod()
    peak = equity.cummax()
    drawdown = float((equity / peak - 1).min()) if len(equity) else 0.0
    return float(equity.iloc[-1]) if len(equity) else 1.0, drawdown


def score(records: list[dict]) -> dict:
    frame = build_rows(records)
    if frame.empty:
        return {"n": 0}
    dates = frame["date"]

    summary: dict = {
        "n": int(len(frame)),
        "series": int(frame[["symbol", "tf"]].drop_duplicates().shape[0]),
        "hit_1": float(frame["hit_1"].mean()),
        "hit_mid": float(frame["hit_mid"].mean()),
        "hit_final": float(frame["hit_final"].mean()),
        "coverage_50": float(frame["in50"].mean()),
        "coverage_80": float(frame["in80"].mean()),
        "mae_pct": float(frame["mae"].mean() * 100),
        "pinball_pct": float(frame["pinball"].mean() * 100),
        "signals": int((frame["signal"] != 0).sum()),
        "signal_share": float((frame["signal"] != 0).mean()),
        "positions_taken": int((frame["position"] != 0).sum()),
        "positions_skipped_overlap": int(frame["blocked"].sum()),
    }

    for name, fee in FEE_SCENARIOS.items():
        cost = frame["position"].abs() * fee * 2      # entrata + uscita
        net = frame["raw_return"] - cost
        equity, drawdown = equity_stats(net, dates)
        taken = frame["position"] != 0
        summary[f"sum_returns_{name}"] = float(net.sum())
        summary[f"equity_{name}"] = equity
        summary[f"drawdown_{name}"] = drawdown
        summary[f"mean_trade_{name}"] = float(net[taken].mean()) if taken.any() else 0.0
        summary[f"win_rate_{name}"] = float((net[taken] > 0).mean()) if taken.any() else 0.0

    # buy & hold vero: per ogni serie, primo prezzo del periodo → ultimo esito realizzato
    hold = (frame.sort_values("anchor").groupby(["symbol", "tf"])
            .agg(first_price=("last", "first"), last_price=("realized_final", "last")))
    hold["return"] = hold["last_price"] / hold["first_price"] - 1
    summary["buy_hold_mean"] = float(hold["return"].mean())
    summary["buy_hold_worst"] = float(hold["return"].min())
    summary["buy_hold_best"] = float(hold["return"].max())
    summary["buy_hold_per_series"] = {f"{sym} {tf}": float(ret)
                                      for (sym, tf), ret in hold["return"].items()}

    summary["per_tf"] = {}
    for tf, group in frame.groupby("tf"):
        net = group["raw_return"] - group["position"].abs() * 2 * FEE_SCENARIOS["spot_0.1%"]
        equity, drawdown = equity_stats(net, group["date"])
        taken = group["position"] != 0
        summary["per_tf"][tf] = {
            "n": int(len(group)),
            "hit_final": float(group["hit_final"].mean()),
            "coverage_80": float(group["in80"].mean()),
            "positions": int(taken.sum()),
            "equity_spot": equity,
            "drawdown_spot": drawdown,
            "mean_trade_spot": float(net[taken].mean()) if taken.any() else 0.0,
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
        f"- MAE mediana **{summary['mae_pct']:.2f}%**, pinball normalizzato medio "
        f"**{summary['pinball_pct']:.3f}%** del prezzo",
        f"- Segnali **{summary['signals']}** su {summary['n']} ({summary['signal_share']:.1%}); "
        f"posizioni aperte **{summary['positions_taken']}**, segnali saltati perché una posizione "
        f"era ancora aperta **{summary['positions_skipped_overlap']}**",
        "",
        "| scenario fee | somma dei ritorni | equity | max DD | media/trade | win rate |",
        "|---|---|---|---|---|---|",
    ]
    for name in FEE_SCENARIOS:
        lines.append(
            f"| {name} | {summary[f'sum_returns_{name}']:+.2f} | "
            f"{summary[f'equity_{name}']:.3f}x | {summary[f'drawdown_{name}']:.1%} | "
            f"{summary[f'mean_trade_{name}']:+.3%} | {summary[f'win_rate_{name}']:.1%} |")
    lines += [
        "",
        f"Buy & hold vero (primo prezzo → ultimo esito, per serie): media "
        f"**{summary['buy_hold_mean']:+.1%}**, peggiore {summary['buy_hold_worst']:+.1%}, "
        f"migliore {summary['buy_hold_best']:+.1%}",
        "",
        "| timeframe | n | posizioni | direzione | copertura 80% | equity spot | max DD | media/trade |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for tf, block in summary["per_tf"].items():
        lines.append(f"| {tf} | {block['n']} | {block['positions']} | {block['hit_final']:.1%} | "
                     f"{block['coverage_80']:.1%} | {block['equity_spot']:.3f}x | "
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
    print(to_markdown(summary))
    out = Path(args.out) if args.out else RESULTS / args.variant / "backtest.json"
    out.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"\nscritto {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
