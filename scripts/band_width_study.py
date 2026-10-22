#!/usr/bin/env python3
"""La larghezza delle bande di Kronos prevede la volatilità reale?

Per ogni forecast confronta tre grandezze sullo stesso orizzonte:
- **banda prevista**: (p90 − p10) / prezzo, al passo finale;
- **volatilità realizzata**: (max − min) / prezzo sui prezzi realizzati dell'orizzonte;
- **baseline storica**: (max − min) / prezzo sulle ultime N candele *prima* dell'ancora
  (N = orizzonte), cioè "la volatilità appena passata".

Se Kronos serve a qualcosa sulle bande, la banda prevista deve correlare con la volatilità
realizzata **più** della baseline storica. Correlazioni calcolate per serie (Pearson e
Spearman) e in pool, per timeframe.

Uso:
    python scripts/band_width_study.py --variant small512
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


def load_frame(symbol: str, tf: str) -> pd.DataFrame:
    frame = pd.read_parquet(DATA / f"{symbol}_{tf}.parquet").sort_values("open_time")
    return frame.iloc[:-1].reset_index(drop=True)


def historical_range(frame: pd.DataFrame, anchor: pd.Timestamp, horizon: int) -> float | None:
    """Range delle ultime `horizon` candele chiuse *prima* dell'ancora."""
    before = frame[frame["open_time"] <= anchor]
    if len(before) < horizon + 1:
        return None
    window = before.iloc[-horizon:]
    last = float(window["close"].iloc[-1])
    if last <= 0:
        return None
    return float((window["high"].max() - window["low"].min()) / last)


def spearman(a: pd.Series, b: pd.Series) -> float:
    """Spearman senza scipy: correlazione di Pearson sui ranghi (i pareggi prendono la media)."""
    return float(a.rank().corr(b.rank()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", default="small512")
    parser.add_argument("--out", default="docs/phase3-band-width.md")
    args = parser.parse_args(argv)

    rows = []
    for path in sorted((RESULTS / args.variant).glob("*.jsonl")):
        tf = path.name.split("_")[0]
        symbol = path.stem.split("_", 1)[1]
        frame = load_frame(symbol, tf)
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                realized = np.asarray(record.get("realized", []), dtype=float)
                if len(realized) != record.get("horizon"):
                    continue
                last = record["last_price"]
                bands = {int(k[1:]): np.asarray(v, dtype=float)
                         for k, v in record["bands"].items()}
                anchor = pd.Timestamp(record["anchor"])
                hist = historical_range(frame, anchor, record["horizon"])
                if hist is None:
                    continue
                rows.append({
                    "symbol": symbol, "tf": tf,
                    "pred_width": float((bands[90][-1] - bands[10][-1]) / last),
                    "hist_range": hist,
                    "real_range": float((realized.max() - realized.min()) / last),
                    "real_std": float(np.std(np.diff(np.log(realized))) *
                                      np.sqrt(len(realized))),
                })

    frame = pd.DataFrame(rows)
    if frame.empty:
        print("nessun record utilizzabile")
        return 1

    def corr(group: pd.DataFrame) -> dict:
        pred = group["pred_width"]
        hist = group["hist_range"]
        real = group["real_range"]
        out = {
            "n": int(len(group)),
            "pearson_pred": float(pred.corr(real)),
            "spearman_pred": spearman(pred, real),
            "pearson_hist": float(hist.corr(real)),
            "spearman_hist": spearman(hist, real),
            "ratio_median": float((real / pred).median()),
        }
        return out

    summary = {"variant": args.variant, "pooled": corr(frame),
               "per_series": {}, "per_tf": {}}
    for (symbol, tf), group in frame.groupby(["symbol", "tf"]):
        summary["per_series"][f"{symbol} {tf}"] = corr(group)
    for tf, group in frame.groupby("tf"):
        summary["per_tf"][tf] = corr(group)

    lines = [
        "# Fase 3 — larghezza bande vs volatilità realizzata",
        "",
        f"Campione: **{summary['pooled']['n']}** forecast "
        f"({args.variant}), serie 20, una previsione al giorno.",
        "",
        "Grandezze confrontate sullo stesso orizzonte: banda prevista (p90−p10)/prezzo,",
        "range realizzato (max−min)/prezzo, baseline storica = range delle N candele",
        "precedenti l'ancora (N = orizzonte).",
        "",
        "## In pool (tutte le serie)",
        "",
        "| misura | Pearson | Spearman |",
        "|---|---|---|",
        f"| banda prevista vs range realizzato | {summary['pooled']['pearson_pred']:.3f} | "
        f"{summary['pooled']['spearman_pred']:.3f} |",
        f"| baseline storica vs range realizzato | {summary['pooled']['pearson_hist']:.3f} | "
        f"{summary['pooled']['spearman_hist']:.3f} |",
        "",
        f"Rapporto mediano realizzato/previsto: **{summary['pooled']['ratio_median']:.2f}** "
        "(1,00 = banda giusta in mediana).",
        "",
        "## Per timeframe",
        "",
        "| tf | n | Pearson banda | Spearman banda | Pearson storica | Spearman storica |",
        "|---|---|---|---|---|---|",
    ]
    for tf, block in summary["per_tf"].items():
        lines.append(f"| {tf} | {block['n']} | {block['pearson_pred']:.3f} | "
                     f"{block['spearman_pred']:.3f} | {block['pearson_hist']:.3f} | "
                     f"{block['spearman_hist']:.3f} |")
    lines += ["", "## Per serie", "",
              "| serie | n | Pearson banda | Spearman banda | Pearson storica | Spearman storica |",
              "|---|---|---|---|---|---|"]
    for name, block in summary["per_series"].items():
        lines.append(f"| {name} | {block['n']} | {block['pearson_pred']:.3f} | "
                     f"{block['spearman_pred']:.3f} | {block['pearson_hist']:.3f} | "
                     f"{block['spearman_hist']:.3f} |")
    text = "\n".join(lines)
    print(text)
    Path(args.out).write_text(text + "\n", encoding="utf-8")
    (RESULTS / args.variant / "band-width.json").write_text(
        json.dumps(summary, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
