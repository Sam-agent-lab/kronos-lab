#!/usr/bin/env python3
"""Fase finale — Giudice A (contesto) contro Giudice B (contesto + Kronos, con riponderazione dei path).

    python scripts/path_judge_model.py --stage dev
    python scripts/path_judge_model.py --stage lockbox     # richiede docs/op-review-pathjudge.md

Perché due giudici: se B batte A, Kronos aggiunge informazione; se B ≈ A, Kronos non aggiunge
niente e il valore viene solo dal contesto di mercato.

Target (come in Fase 7-lite): 1 se il trade **nella direzione di Kronos** è profittevole dopo
fee maker 0,02% per lato.

Validazione: walk-forward in espansione con **purge di 3 giorni** (≥ 24 h richieste), soglia
scelta solo in validation, controllo con etichette mescolate, baseline logistica, posizioni non
sovrapposte per serie, intervalli di confidenza con **block bootstrap** a blocchi di 7 giorni.
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "path_judge_dataset.parquet"
PATHS = ROOT / "paths"
OUT = ROOT / "results" / "path_judge"
OP_REVIEW = ROOT / "docs" / "op-review-pathjudge.md"

MAKER = 0.0002
SPOT = 0.001
PURGE_DAYS = 3
MIN_TRADES = 150
FOLDS = 5
SEED = 11
BLOCK_DAYS = 7
STEP = {"1h": 60, "4h": 240}

CONTEXT_NUMERIC = [
    "vol_24", "vol_96", "range_24", "range_96", "volume_rel_24h", "volume_rel_7d",
    "px_vs_ema50", "px_vs_ema200", "ema50_vs_ema200", "rsi14", "atr14", "ret_24",
    "funding_rate", "funding_mean3", "hour", "weekday",
]
KRONOS_NUMERIC = [
    "prob_up", "median_ret", "band80", "band50", "band80_step1", "skew_band",
    "path_final_std", "path_final_skew", "path_final_p10", "path_final_p90",
    "path_up_share", "path_agreement_step1", "path_maxdd_median", "path_vol_median",
    "prob_up_reweighted", "prob_up_gap",
]
CATEGORICAL = ["symbol", "tf"]
# fonti esterne: si aggiungono solo se presenti nel dataset (copertura completa del periodo)
EXTERNAL_COLUMNS = ["btc_netflow_pct", "eth_netflow_pct", "stable_change_7d",
                    "ndx_ret_1d", "ndx_ret_5d", "dxy_ret_1d", "dxy_ret_5d"]

PARAMS = {
    "objective": "binary", "learning_rate": 0.03, "num_leaves": 7, "max_depth": 3,
    "min_child_samples": 80, "subsample": 0.8, "subsample_freq": 1,
    "colsample_bytree": 0.7, "reg_lambda": 5.0, "reg_alpha": 1.0,
    "n_estimators": 300, "random_state": SEED, "verbose": -1,
}
PATH_PARAMS = dict(PARAMS)
PATH_PARAMS.update({"num_leaves": 15, "min_child_samples": 200, "n_estimators": 200})


def load_dataset() -> tuple[pd.DataFrame, list[str]]:
    frame = pd.read_parquet(DATA).sort_values("anchor").reset_index(drop=True)
    for column in CATEGORICAL:
        frame[column] = frame[column].astype("category")
    context = CONTEXT_NUMERIC + [c for c in EXTERNAL_COLUMNS
                                 if c in frame.columns and frame[c].notna().mean() > 0.95]
    return frame, context


def load_path_rows() -> pd.DataFrame:
    """Una riga per (forecast, path): feature del singolo path + etichetta di direzione."""
    frames = []
    for directory in sorted(glob.glob(str(PATHS / "*_*"))):
        path = Path(directory)
        if not (path / "meta.jsonl").is_file():
            continue
        symbol, tf = path.name.split("_", 1)
        if tf not in STEP:
            continue
        metas = [json.loads(line) for line in path.joinpath("meta.jsonl").read_text().splitlines()
                 if line.strip()]
        shards = sorted(path.glob("paths_*.npz"))
        if not shards:
            continue
        arrays = np.concatenate([np.load(shard)["paths"] for shard in shards])
        if len(arrays) != len(metas):
            continue
        last = np.array([m["last_price"] for m in metas])[:, None]
        rets = arrays[:, :, -1] / last - 1
        cummax = np.maximum.accumulate(arrays, axis=2)
        maxdd = ((cummax - arrays) / cummax).max(axis=2)
        vol = np.std(np.diff(np.log(arrays), axis=2), axis=2)
        slope = arrays[:, :, -1] / arrays[:, :, 0] - 1
        up = (rets > 0).astype(np.int8)
        realized = np.array([m["realized_final"] if "realized_final" in m else np.nan
                             for m in metas])
        frames.append(pd.DataFrame({
            "anchor": np.repeat(pd.to_datetime([m["anchor"] for m in metas]), 30),
            "symbol": symbol, "tf": tf,
            "path_ret": rets.ravel(), "path_maxdd": maxdd.ravel(),
            "path_vol": vol.ravel(), "path_slope": slope.ravel(),
            "path_up": up.ravel(),
            "prob_up": np.repeat(np.array([m["prob_up"] for m in metas]), 30),
        }))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def path_weights(train_paths: pd.DataFrame, valid_paths: pd.DataFrame,
                 train_frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Allena lo scorer dei path e restituisce p_credibile per i path di training e validation."""
    train_labels = train_paths["path_up"].to_numpy() == train_paths["_real_up"].to_numpy()
    features = ["path_ret", "path_maxdd", "path_vol", "path_slope", "path_up", "prob_up",
                "vol_24", "range_24", "rsi14", "atr14", "funding_rate"]
    model = lgb.LGBMClassifier(**PATH_PARAMS)
    model.fit(train_paths[features], train_labels.astype(int))
    return (model.predict_proba(train_paths[features])[:, 1],
            model.predict_proba(valid_paths[features])[:, 1])


def attach_reweighted(frame: pd.DataFrame, path_rows: pd.DataFrame) -> pd.DataFrame:
    """prob_up riponderata: media dei path pesata per la loro credibilità."""
    weighted = (path_rows.assign(w=path_rows["w"] * path_rows["path_up"])
                .groupby(["anchor", "symbol", "tf"], as_index=False)
                .agg(w_sum=("w", "sum"), w_up=("w", "sum")))
    weighted["prob_up_reweighted"] = weighted["w_up"] / weighted["w_sum"].replace(0, np.nan)
    merged = frame.merge(weighted[["anchor", "symbol", "tf", "prob_up_reweighted"]],
                         on=["anchor", "symbol", "tf"], how="left")
    merged["prob_up_gap"] = merged["prob_up_reweighted"] - merged["prob_up"]
    return merged


def wilson_block_bootstrap(frame: pd.DataFrame, block_days: int = BLOCK_DAYS,
                           draws: int = 2000) -> dict:
    """CI con block bootstrap a blocchi di giorni, calcolato su aggregati giornalieri.

    Prima ricampionava DataFrame interi: 2.000 ricampionamenti per ogni soglia erano lentissimi.
    Così si ricampionano solo quattro numeri per giorno (trade, hit, somma e numero di rendimenti).
    """
    empty = {"win_low": float("nan"), "win_high": float("nan"),
             "ret_low": float("nan"), "ret_high": float("nan")}
    if frame.empty:
        return empty
    daily = (frame.assign(day=pd.to_datetime(frame["anchor"]).dt.floor("D"))
             .groupby("day")
             .agg(trades=("target", "size"), hits=("target", "sum"),
                  ret_sum=("net_return_maker", "sum"), ret_n=("net_return_maker", "size")))
    if len(daily) < 2:
        return empty
    values = daily.to_numpy(dtype=float)
    blocks = [values[i:i + block_days] for i in range(0, len(values), block_days)]
    if len(blocks) < 2:
        return empty
    sums = np.array([block.sum(axis=0) for block in blocks])       # (n_blocchi, 4)
    rng = np.random.default_rng(SEED)
    picks = rng.integers(0, len(sums), size=(draws, len(sums)))
    totals = sums[picks].sum(axis=1)                               # (draws, 4)
    wins = np.divide(totals[:, 1], totals[:, 0], out=np.full(draws, np.nan),
                     where=totals[:, 0] > 0)
    rets = np.divide(totals[:, 2], totals[:, 3], out=np.full(draws, np.nan),
                     where=totals[:, 3] > 0)
    return {
        "win_low": float(np.nanpercentile(wins, 2.5)),
        "win_high": float(np.nanpercentile(wins, 97.5)),
        "ret_low": float(np.nanpercentile(rets, 2.5)),
        "ret_high": float(np.nanpercentile(rets, 97.5)),
    }


def non_overlapping(frame: pd.DataFrame) -> pd.DataFrame:
    """Una posizione per serie alla volta: niente trade sovrapposti sullo stesso simbolo/tf.

    Versione vettorizzata: si costruisce prima l'array degli "open until" per serie e si scarta
    un indice quando il suo `take` cade dentro una posizione già aperta.
    """
    if frame.empty:
        return frame
    frame = frame.sort_values(["symbol", "tf", "anchor"]).reset_index(drop=True)
    keep = np.zeros(len(frame), dtype=bool)
    for _, index in frame.groupby(["symbol", "tf"], sort=False).indices.items():
        index = np.asarray(index)
        open_until = None
        for position in index:
            row = frame.iloc[position]
            if not row["take"]:
                continue
            anchor = pd.Timestamp(row["anchor"])
            if open_until is not None and anchor < open_until:
                continue
            keep[position] = True
            open_until = anchor + pd.Timedelta(minutes=STEP[row["tf"]] * int(row["horizon"]))
    return frame[keep]


def summarise(frame: pd.DataFrame) -> dict:
    taken = non_overlapping(frame.assign(take=frame["p_lgb"] >= frame["threshold"]))
    taken = taken[taken["take"]]
    n = len(taken)
    hits = int(taken["target"].sum()) if n else 0
    boot = wilson_block_bootstrap(taken)
    net = taken["net_return_maker"] if n else pd.Series(dtype=float)
    equity = (1 + net).cumprod() if n else pd.Series(dtype=float)
    drawdown = float((equity / equity.cummax() - 1).min()) if n else 0.0
    spot = net - 2 * (SPOT - MAKER)
    return {
        "trades": n,
        "win_rate": hits / n if n else float("nan"),
        "win_ci_low": boot["win_low"], "win_ci_high": boot["win_high"],
        "mean_net_maker": float(net.mean()) if n else float("nan"),
        "ret_ci_low": boot["ret_low"], "ret_ci_high": boot["ret_high"],
        "equity_maker": float(equity.iloc[-1]) if n else float("nan"),
        "max_dd_maker": drawdown,
        "mean_net_spot": float(spot.mean()) if n else float("nan"),
        "equity_spot": float((1 + spot).cumprod().iloc[-1]) if n else float("nan"),
    }


def fit_and_score(train: pd.DataFrame, valid: pd.DataFrame, features: list[str]) -> np.ndarray:
    numeric = [f for f in features if f not in CATEGORICAL]
    x_train = train[features].copy()
    x_valid = valid[features].copy()
    x_train[numeric] = x_train[numeric].fillna(0)     # le categoriche non si toccano
    x_valid[numeric] = x_valid[numeric].fillna(0)
    for column in CATEGORICAL:                        # i merge perdono il dtype category
        x_train[column] = x_train[column].astype("category")
        x_valid[column] = x_valid[column].astype("category")
    model = lgb.LGBMClassifier(**PARAMS)
    model.fit(x_train, train["target"])
    return model.predict_proba(x_valid)[:, 1]


def logit_score(train: pd.DataFrame, valid: pd.DataFrame, numeric: list[str]) -> np.ndarray:
    def matrix(part: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
        base = part[numeric].fillna(0)
        dummies = pd.get_dummies(part[CATEGORICAL].astype(str))
        return pd.concat([base, dummies], axis=1).reindex(columns=columns, fill_value=0)

    pipe = make_pipeline(StandardScaler(),
                         LogisticRegression(max_iter=2000, C=0.1, class_weight="balanced",
                                            random_state=SEED))
    train_matrix = matrix(train, list(pd.concat(
        [train[numeric].fillna(0), pd.get_dummies(train[CATEGORICAL].astype(str))], axis=1)
        .columns))
    pipe.fit(train_matrix, train["target"])
    return pipe.predict_proba(matrix(valid, list(train_matrix.columns)))[:, 1]


def build_folds(frame: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.DataFrame, pd.DataFrame]]:
    start, end = frame["anchor"].min(), frame["anchor"].max()
    span_days = (end - start).days
    folds = []
    for index in range(FOLDS):
        edge = start + pd.Timedelta(days=span_days * (index + 1) / (FOLDS + 1))
        train = frame[frame["anchor"] < edge - pd.Timedelta(days=PURGE_DAYS)]
        valid = frame[(frame["anchor"] >= edge)
                      & (frame["anchor"] < edge + pd.Timedelta(days=span_days / (FOLDS + 1)))]
        if len(train) > 800 and len(valid) > 100:
            folds.append((edge, train, valid))
    return folds


def run_validation(frame: pd.DataFrame, path_rows: pd.DataFrame, context: list[str]) -> dict:
    blocks = []
    for edge, train, valid in build_folds(frame):
        train_paths = path_rows[path_rows["anchor"].isin(train["anchor"])].copy()
        valid_paths = path_rows[path_rows["anchor"].isin(valid["anchor"])].copy()
        train_real = train.set_index(["anchor", "symbol", "tf"])["realized_final"]
        train_paths["_real_up"] = [train_real.get((a, s, t), np.nan) > 0
                                   for a, s, t in zip(train_paths["anchor"],
                                                      train_paths["symbol"],
                                                      train_paths["tf"])]
        train_paths = train_paths.dropna(subset=["_real_up"])
        for column in ("vol_24", "range_24", "rsi14", "atr14", "funding_rate"):
            mapping = train.set_index(["anchor", "symbol", "tf"])[column]
            train_paths[column] = [mapping.get((a, s, t), np.nan)
                                   for a, s, t in zip(train_paths["anchor"],
                                                      train_paths["symbol"],
                                                      train_paths["tf"])]
            mapping_v = valid.set_index(["anchor", "symbol", "tf"])[column]
            valid_paths[column] = [mapping_v.get((a, s, t), np.nan)
                                   for a, s, t in zip(valid_paths["anchor"],
                                                      valid_paths["symbol"],
                                                      valid_paths["tf"])]
        train_paths["w"], valid_paths["w"] = path_weights(train_paths, valid_paths, frame)
        train_b = attach_reweighted(train, train_paths)
        valid_b = attach_reweighted(valid, valid_paths)

        features_a = context + CATEGORICAL
        features_b = context + KRONOS_NUMERIC + CATEGORICAL
        block = valid[["anchor", "symbol", "tf", "horizon", "target",
                       "net_return_maker", "gross_return"]].copy()
        block["p_a"] = fit_and_score(train, valid, features_a)
        block["p_b"] = fit_and_score(train_b, valid_b, features_b)
        block["p_logit_a"] = logit_score(train, valid, context)
        block["p_logit_b"] = logit_score(train_b, valid_b, context + KRONOS_NUMERIC)

        rng = np.random.default_rng(SEED + len(blocks))
        shuffled = train_b.copy()          # stesse colonne di B, etichette mescolate
        shuffled["target"] = rng.permutation(shuffled["target"].to_numpy())
        block["p_shuffled"] = fit_and_score(shuffled, valid_b, features_b)
        block["fold"] = str(edge.date())
        blocks.append(block)
        print(json.dumps({"fold": str(edge.date()), "train": len(train), "valid": len(valid),
                          "base_rate": round(float(valid["target"].mean()), 4)}), flush=True)
    if not blocks:
        return {"pooled": pd.DataFrame()}
    return {"pooled": pd.concat(blocks, ignore_index=True)}


def choose_threshold(pooled: pd.DataFrame, column: str) -> tuple[float, list[dict]]:
    grid = []
    for threshold in np.arange(0.45, 0.76, 0.01):
        block = summarise(pooled.assign(p_lgb=pooled[column], threshold=float(threshold)))
        if block["trades"] >= MIN_TRADES:
            grid.append({"threshold": float(threshold), **block})
    if not grid:
        return 0.5, grid
    return max(grid, key=lambda item: item["mean_net_maker"])["threshold"], grid


def stage_dev() -> int:
    frame, context = load_dataset()
    dev = frame[~frame["is_lockbox"]].reset_index(drop=True)
    path_rows = load_path_rows()
    path_rows = path_rows[path_rows["anchor"] < dev["anchor"].max()]
    print(json.dumps({"stage": "dev", "rows": len(dev), "path_rows": len(path_rows),
                      "base_rate": round(float(dev["target"].mean()), 4),
                      "to": str(dev["anchor"].max())}), flush=True)

    print(json.dumps({"context_features": context}), flush=True)
    if len(dev) < 2000:
        print(json.dumps({"stage": "dev", "status": "dati insufficienti",
                          "rows": int(len(dev)),
                          "note": "il run di generazione non ha ancora prodotto abbastanza "
                                  "serie complete; rilanciare a fine run"}))
        return 0
    pooled = run_validation(dev, path_rows, context)["pooled"]
    report = {"stage": "dev", "rows": int(len(dev)), "pooled_rows": int(len(pooled))}
    for column, name in (("p_a", "judge_a"), ("p_b", "judge_b")):
        threshold, grid = choose_threshold(pooled, column)
        report[name] = {"threshold": threshold,
                        **summarise(pooled.assign(p_lgb=pooled[column], threshold=threshold)),
                        "grid": grid}
    report["kronos_unfiltered"] = {"threshold": 0.0,
                                   **summarise(pooled.assign(p_lgb=1.0, threshold=0.0))}
    report["shuffled_control"] = {"threshold": report["judge_b"]["threshold"],
                                  **summarise(pooled.assign(p_lgb=pooled["p_shuffled"],
                                                            threshold=report["judge_b"]["threshold"]))}
    report["logit_a"] = {"threshold": report["judge_a"]["threshold"],
                         **summarise(pooled.assign(p_lgb=pooled["p_logit_a"],
                                                   threshold=report["judge_a"]["threshold"]))}
    report["logit_b"] = {"threshold": report["judge_b"]["threshold"],
                         **summarise(pooled.assign(p_lgb=pooled["p_logit_b"],
                                                   threshold=report["judge_b"]["threshold"]))}
    OUT.mkdir(parents=True, exist_ok=True)
    pooled.to_parquet(OUT / "validation_predictions.parquet", index=False)
    (OUT / "dev-report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps({key: report[key] for key in
                      ("judge_a", "judge_b", "kronos_unfiltered", "shuffled_control")},
                     indent=1, default=str)[:3000])
    return 0


def stage_lockbox() -> int:
    if not OP_REVIEW.is_file():
        print(json.dumps({"error": "manca docs/op-review-pathjudge.md: serve la review Opus "
                                   "sul leakage prima del lockbox"}))
        return 2
    print(json.dumps({"error": "lockbox non ancora sbloccato: attende la review"}))
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["dev", "lockbox"], required=True)
    args = parser.parse_args(argv)
    return stage_dev() if args.stage == "dev" else stage_lockbox()


if __name__ == "__main__":
    raise SystemExit(main())
