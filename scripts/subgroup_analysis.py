#!/usr/bin/env python3
"""Accuratezza direzionale per sottogruppi, con intervalli di confidenza e controllo FDR.

Gruppi: fascia di prob_up (simmetrica), regime (TRENDING vs CHOPPY), fascia oraria UTC
(Asia/Europa/USA), asset, timeframe.

Per ogni gruppo: n, accuratezza al passo finale con IC 95% di Wilson, rendimento medio netto
con fee maker 0,02% per lato. Si segnalano solo gruppi con almeno 200 forecast e accuratezza
**significativamente** sopra il 50% dopo correzione di Benjamini-Hochberg (FDR 5%): con decine
di gruppi qualcuno sembra bravo per puro caso.

Uso:
    python scripts/subgroup_analysis.py --variant small512
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import backtest as bt

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
MAKER = bt.FEE_SCENARIOS["futures_maker_0.02%"]
MIN_N = 200
HOUR_BANDS = [("Asia 00-08", 0, 8), ("Europa 08-16", 8, 16), ("USA 16-24", 16, 24)]
PROB_BUCKETS = [(-1.01, 0.2, "prob_up < 0,20"), (-0.01, 0.2, "prob_up < 0,20"),
                (0.2, 0.3, "prob_up 0,20-0,30"), (0.3, 0.4, "prob_up 0,30-0,40"),
                (0.4, 0.5, "prob_up 0,40-0,50"), (0.5, 0.6, "prob_up 0,50-0,60"),
                (0.6, 0.7, "prob_up 0,60-0,70"), (0.7, 0.8, "prob_up 0,70-0,80"),
                (0.8, 1.01, "prob_up > 0,80")]


def wilson(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    phat = hits / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def one_sided_p(hits: int, n: int) -> float:
    """P(X >= hits) sotto H0 p=0,5, approssimazione normale con correzione di continuità."""
    if n == 0:
        return 1.0
    z = (hits - 0.5 * n - 0.5) / math.sqrt(n * 0.25)
    return 0.5 * math.erfc(z / math.sqrt(2))


def regimes(prob_up: float) -> str:
    if prob_up >= 0.70:
        return "TRENDING_UP"
    if prob_up <= 0.30:
        return "TRENDING_DOWN"
    return "CHOPPY"


def build_frame(variant: str) -> pd.DataFrame:
    records = bt.load_records(variant)
    frame = bt.build_rows(records)
    if frame.empty:
        return frame
    frame["hour"] = pd.to_datetime(frame["anchor"]).dt.hour
    frame["hour_band"] = frame["hour"].map(
        lambda h: next((name for name, lo, hi in HOUR_BANDS if lo <= h < hi), "?"))
    frame["regime"] = frame["prob_up"].map(regimes)
    frame["regime_group"] = frame["regime"].map(
        lambda value: "TRENDING" if value.startswith("TRENDING") else "CHOPPY")

    def bucket(prob: float) -> str:
        for lo, hi, label in PROB_BUCKETS:
            if lo < prob <= hi:
                return label
        return "prob_up 0,40-0,50"

    frame["prob_bucket"] = frame["prob_up"].map(bucket)
    taken = frame["position"] != 0
    frame["net_maker"] = np.where(
        taken,
        frame["raw_return"] - frame["position"].abs() * 2 * MAKER,
        0.0)
    return frame


def stats(frame: pd.DataFrame, mask: pd.Series) -> dict | None:
    group = frame[mask]
    if group.empty:
        return None
    n = int(len(group))
    hits = int(group["hit_final"].sum())
    low, high = wilson(hits, n)
    taken = group["position"] != 0
    return {
        "n": n,
        "accuracy": hits / n,
        "ci_low": low,
        "ci_high": high,
        "p_value": one_sided_p(hits, n),
        "positions": int(taken.sum()),
        "mean_net_maker": float(group.loc[taken, "net_maker"].mean()) if taken.any() else 0.0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", default="small512")
    parser.add_argument("--min-n", type=int, default=MIN_N)
    parser.add_argument("--fdr", type=float, default=0.05)
    args = parser.parse_args(argv)

    frame = build_frame(args.variant)
    if frame.empty:
        print("nessun dato")
        return 1

    dimensions = {
        "fascia prob_up": "prob_bucket",
        "regime": "regime_group",
        "fascia oraria UTC": "hour_band",
        "asset": "symbol",
        "timeframe": "tf",
    }
    rows = []
    for title, column in dimensions.items():
        for value, group in frame.groupby(column):
            block = stats(frame, frame[column] == value)
            if block is None:
                continue
            block.update({"dimensione": title, "gruppo": str(value)})
            rows.append(block)

    report = pd.DataFrame(rows)
    report["p_bh"] = 1.0
    # Benjamini-Hochberg su tutti i gruppi con n sufficiente
    eligible = report["n"] >= args.min_n
    if eligible.any():
        ordered = report.loc[eligible].sort_values("p_value")
        m = len(ordered)
        threshold = args.fdr * np.arange(1, m + 1) / m
        passed = ordered["p_value"].to_numpy() <= threshold
        cutoff = ordered["p_value"].to_numpy()[np.where(passed)[0].max()] if passed.any() else -1
        report.loc[eligible, "p_bh"] = report.loc[eligible, "p_value"].apply(
            lambda value: min(1.0, value * m / max(1, (report.loc[eligible, "p_value"] <= value).sum())))
        report.loc[eligible, "significant"] = report.loc[eligible, "p_value"] <= cutoff
    report["significant"] = report.get("significant", False)

    summary = {
        "variant": args.variant,
        "n_total": int(len(frame)),
        "min_n": args.min_n,
        "fdr": args.fdr,
        "groups": report.to_dict(orient="records"),
    }
    out = RESULTS / args.variant / "subgroups.json"
    out.write_text(json.dumps(summary, indent=1), encoding="utf-8")

    lines = [f"# Sottogruppi — {args.variant}", "",
             f"{len(frame)} forecast; gruppi con almeno {args.min_n} forecast, "
             f"FDR {args.fdr:.0%} (Benjamini-Hochberg).", "",
             "| dimensione | gruppo | n | posizioni | accuratezza | IC 95% | p | p BH | "
             "rendimento medio maker |", "|---|---|---|---|---|---|---|---|---|"]
    ordered = report.sort_values(["dimensione", "accuracy"], ascending=[True, False])
    for _, row in ordered.iterrows():
        lines.append(
            f"| {row['dimensione']} | {row['gruppo']} | {row['n']} | {row['positions']} | "
            f"{row['accuracy']:.1%} | {row['ci_low']:.1%}–{row['ci_high']:.1%} | "
            f"{row['p_value']:.4f} | {row['p_bh']:.3f} | {row['mean_net_maker']:+.3%} |")
    flagged = report[(report["n"] >= args.min_n) & (report["accuracy"] > 0.5)
                     & (report["significant"])]
    lines += ["", "## Gruppi segnalati (n ≥ %d, accuratezza sopra il 50%% e significativa)"
              % args.min_n, ""]
    if flagged.empty:
        lines.append("**Nessuno.** Nessun gruppo con campione sufficiente resta significativo "
                     "dopo la correzione per i test multipli.")
    else:
        for _, row in flagged.iterrows():
            lines.append(f"- {row['dimensione']} · {row['gruppo']}: n={row['n']}, "
                         f"accuratezza {row['accuracy']:.1%} "
                         f"(IC {row['ci_low']:.1%}–{row['ci_high']:.1%}), "
                         f"p BH {row['p_bh']:.3f}, rendimento maker "
                         f"{row['mean_net_maker']:+.3%}")
    text = "\n".join(lines)
    print(text)
    (ROOT / "docs" / "phase3-subgroups.generated.md").write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
