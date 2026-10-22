#!/usr/bin/env python3
"""Fase 7-lite — il "giudice" che decide se fidarsi di Kronos.

Due stadi separati, di proposito:

    python scripts/judge_model.py --stage dev        # walk-forward + soglia + controllo etichette
    python scripts/judge_model.py --stage lockbox    # UNA sola valutazione finale

Lo stadio `lockbox` si rifiuta di partire se non esiste `docs/op-review-phase7.md`: la review
di Opus sul leakage deve venire **prima** dell'unica valutazione sul lockbox.

Feature usate: solo ciò che è noto al momento del forecast (vedi build_judge_dataset.py).
Open interest **escluso**: Binance conserva solo ~20 giorni di storia pubblica, quindi la
feature esisterebbe solo nel lockbox (leakage di disponibilità, non di informazione).

Success criteria fissati prima: IC 95% del win rate sopra il 50% **e** rendimento positivo dopo
fee maker sul lockbox, con almeno 150 trade.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "judge_dataset.parquet"
OUT = ROOT / "results" / "judge"
OP_REVIEW = ROOT / "docs" / "op-review-phase7.md"

MAKER = 0.0002
SPOT = 0.001
PURGE_DAYS = 3          # etichetta = orizzonte (max 24h) + margine per l'accuratezza rolling
MIN_TRAIN = 1500
MIN_TRADES = 150
SEED = 7

NUMERIC = [
    "prob_up", "median_ret", "band80", "band50", "band80_step1", "agreement", "path_skew",
    "mean_vs_median", "past_acc_30",
    "vol_24", "vol_96", "range_24", "range_96", "volume_rel_24h", "volume_rel_7d",
    "px_vs_ema50", "px_vs_ema200", "ema50_vs_ema200", "rsi14", "atr14",
    "funding_rate", "funding_mean3",
    "hour", "weekday",
]
CATEGORICAL = ["regime", "symbol", "tf"]
FEATURES = NUMERIC + CATEGORICAL

LGB_PARAMS = {
    "objective": "binary",
    "learning_rate": 0.03,
    "num_leaves": 7,             # albero piccolo: pochi dati, tanto rumore
    "max_depth": 3,
    "min_child_samples": 80,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.7,
    "reg_lambda": 5.0,
    "reg_alpha": 1.0,
    "n_estimators": 400,
    "random_state": SEED,
    "verbose": -1,
}


def wilson(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    phat = hits / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * np.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def load() -> pd.DataFrame:
    frame = pd.read_parquet(DATA).sort_values("anchor").reset_index(drop=True)
    for column in CATEGORICAL:
        frame[column] = frame[column].astype("category")
    return frame


def fit_lgb(train: pd.DataFrame) -> lgb.LGBMClassifier:
    model = lgb.LGBMClassifier(**LGB_PARAMS)
    model.fit(train[FEATURES], train["target"])
    return model


def fit_logit(train: pd.DataFrame):
    pipeline = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=2000, C=0.1, class_weight="balanced",
                           random_state=SEED),
    )
    numeric = train[NUMERIC].fillna(train[NUMERIC].median())
    matrix = pd.concat([numeric, pd.get_dummies(train[CATEGORICAL].astype(str))], axis=1)
    pipeline.fit(matrix, train["target"])
    return pipeline, list(matrix.columns)


def logit_predict(model, columns, frame: pd.DataFrame) -> np.ndarray:
    numeric = frame[NUMERIC].fillna(frame[NUMERIC].median())
    matrix = pd.concat([numeric, pd.get_dummies(frame[CATEGORICAL].astype(str))], axis=1)
    matrix = matrix.reindex(columns=columns, fill_value=0)
    return model.predict_proba(matrix)[:, 1]


def walk_forward(frame: pd.DataFrame, folds: int = 5) -> pd.DataFrame:
    """Espansione nel tempo: allena su tutto il passato, valida sul blocco successivo.

    Fra training e validation c'è un cuscinetto di PURGE_DAYS giorni in cui i campioni vengono
    buttati via: l'etichetta di un trade dura fino all'orizzonte, e senza buco il training
    vedrebbe esiti che si sovrappongono all'inizio della validation.
    """
    start, end = frame["anchor"].min(), frame["anchor"].max()
    span = (end - start).days
    edges = [start + pd.Timedelta(days=span * (i + 1) / (folds + 1)) for i in range(folds)]
    results = []
    for edge in edges:
        purge = edge - pd.Timedelta(days=PURGE_DAYS)
        train = frame[frame["anchor"] < purge]
        valid = frame[(frame["anchor"] >= edge)
                      & (frame["anchor"] < edge + pd.Timedelta(days=span / (folds + 1)))]
        if len(train) < MIN_TRAIN or len(valid) < 100:
            continue
        model = fit_lgb(train)
        probability = model.predict_proba(valid[FEATURES])[:, 1]
        block = valid[["anchor", "symbol", "tf", "target", "net_return_maker",
                       "gross_return", "direction"]].copy()
        block["p_judge"] = probability
        block["fold_edge"] = edge
        results.append(block)

        rng = np.random.default_rng(SEED + len(results))
        shuffled = train.copy()
        shuffled["target"] = rng.permutation(shuffled["target"].to_numpy())
        control = fit_lgb(shuffled)
        block_control = block.copy()
        block_control["p_judge"] = control.predict_proba(valid[FEATURES])[:, 1]
        block_control["control"] = "shuffled"
        block["control"] = "real"
        results.append(block_control)
        print(json.dumps({"fold_edge": str(edge), "train": len(train), "valid": len(valid),
                          "valid_rate": round(float(valid["target"].mean()), 4)}), flush=True)
    return pd.concat(results, ignore_index=True)


def summarise(predictions: pd.DataFrame, threshold: float) -> dict:
    taken = predictions[predictions["p_judge"] >= threshold]
    hits = int(taken["target"].sum())
    n = int(len(taken))
    low, high = wilson(hits, n)
    net = taken["net_return_maker"]
    equity = (1 + net).cumprod()
    drawdown = float((equity / equity.cummax() - 1).min()) if len(equity) else 0.0
    spot = net - 2 * (SPOT - MAKER)
    return {
        "threshold": threshold,
        "trades": n,
        "win_rate": hits / n if n else float("nan"),
        "ci_low": low, "ci_high": high,
        "mean_net_maker": float(net.mean()) if n else float("nan"),
        "sum_net_maker": float(net.sum()) if n else float("nan"),
        "equity_maker": float(equity.iloc[-1]) if n else float("nan"),
        "max_dd_maker": drawdown,
        "mean_net_spot": float(spot.mean()) if n else float("nan"),
        "equity_spot": float((1 + spot).cumprod().iloc[-1]) if n else float("nan"),
        "trades_per_day": float(n / max(predictions["anchor"].dt.date.nunique(), 1)),
    }


def choose_threshold(predictions: pd.DataFrame) -> tuple[float, list[dict]]:
    """Soglia scelta SOLO sulla validation: massimo ritorno netto con almeno 150 trade."""
    grid = []
    for threshold in np.arange(0.45, 0.751, 0.01):
        block = summarise(predictions, float(threshold))
        if block["trades"] >= MIN_TRADES:
            grid.append(block)
    if not grid:
        return 0.5, grid
    best = max(grid, key=lambda item: item["sum_net_maker"])
    return best["threshold"], grid


def shap_importance(train: pd.DataFrame) -> list[dict]:
    model = lgb.LGBMClassifier(**LGB_PARAMS)
    model.fit(train[FEATURES], train["target"])
    contrib = model.predict(train[FEATURES], pred_contrib=True)   # TreeSHAP nativo di LightGBM
    values = np.abs(contrib[:, :-1]).mean(axis=0)
    names = model.booster_.feature_name()
    order = np.argsort(values)[::-1]
    return [{"feature": names[i], "mean_abs_shap": float(values[i])} for i in order[:15]]


def stage_dev() -> int:
    frame = load()
    development = frame[~frame["is_lockbox"]].reset_index(drop=True)
    print(json.dumps({"stage": "dev", "rows": len(development),
                      "from": str(development["anchor"].min()),
                      "to": str(development["anchor"].max()),
                      "base_rate": round(float(development["target"].mean()), 4)}), flush=True)

    predictions = walk_forward(development)
    real = predictions[predictions["control"] == "real"]
    control = predictions[predictions["control"] == "shuffled"]

    threshold, grid = choose_threshold(real)
    chosen = summarise(real, threshold)
    base = summarise(real, 0.0)          # "Kronos senza filtro": prende tutti i segnali
    control_block = summarise(control, threshold)

    # baseline logistica sulle stesse fold e stessa soglia scelta
    logit_rows = []
    for edge in sorted(real["fold_edge"].unique()):
        purge = edge - pd.Timedelta(days=PURGE_DAYS)
        train = development[development["anchor"] < purge]
        valid = development[(development["anchor"] >= edge)
                            & (development["anchor"] < edge
                               + pd.Timedelta(days=(development["anchor"].max()
                                                    - development["anchor"].min()).days / 6))]
        if len(train) < MIN_TRAIN or valid.empty:
            continue
        model, columns = fit_logit(train)
        block = valid[["anchor", "target", "net_return_maker"]].copy()
        block["p_judge"] = logit_predict(model, columns, valid)
        logit_rows.append(block)
    logit = pd.concat(logit_rows, ignore_index=True) if logit_rows else pd.DataFrame()
    logit_block = summarise(logit, threshold) if not logit.empty else {}

    importance = shap_importance(development)
    report = {
        "stage": "dev", "threshold": threshold, "chosen": chosen, "unfiltered": base,
        "shuffled_control": control_block, "logistic_baseline": logit_block,
        "success_criteria": {"min_ci_low": 0.5, "positive_net_maker": True,
                             "min_trades": MIN_TRADES},
        "shap_top15": importance,
        "threshold_grid": grid,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "dev-report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("threshold", "chosen", "unfiltered",
                                             "shuffled_control", "logistic_baseline")},
                     indent=1))
    print(json.dumps({"shap_top8": importance[:8]}, indent=1))
    return 0


def stage_lockbox() -> int:
    if not OP_REVIEW.is_file():
        print(json.dumps({"error": "manca docs/op-review-phase7.md: la review di Opus sul "
                                   "leakage deve venire prima della valutazione sul lockbox"}))
        return 2
    frame = load()
    train = frame[~frame["is_lockbox"]].reset_index(drop=True)
    lockbox = frame[frame["is_lockbox"]].reset_index(drop=True)
    dev = json.loads((OUT / "dev-report.json").read_text(encoding="utf-8"))
    threshold = float(dev["threshold"])

    model = fit_lgb(train)
    lockbox = lockbox.assign(p_judge=model.predict_proba(lockbox[FEATURES])[:, 1])
    result = summarise(lockbox, threshold)
    unfiltered = summarise(lockbox, 0.0)

    # buy & hold: primi e ultimi prezzi del lockbox per serie
    hold = (lockbox.sort_values("anchor").groupby(["symbol", "tf"])
            .agg(first=("gross_return", "first"), last=("gross_return", "last")))
    result["lockbox_rows"] = int(len(lockbox))
    result["unfiltered"] = unfiltered
    result["success"] = bool(result["trades"] >= MIN_TRADES
                             and result["ci_low"] > 0.5
                             and result["mean_net_maker"] > 0)
    (OUT / "lockbox-report.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["dev", "lockbox"], required=True)
    args = parser.parse_args(argv)
    return stage_dev() if args.stage == "dev" else stage_lockbox()


if __name__ == "__main__":
    raise SystemExit(main())
