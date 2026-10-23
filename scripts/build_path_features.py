#!/usr/bin/env python3
"""Costruisce il dataset del "path judge": output Kronos (path inclusi) + contesto + fonti esterne.

Una riga per forecast, con il target = 1 se il trade **nella direzione di Kronos**
(`prob_up ≥ 0,60` long, `≤ 0,40` short) è profittevole dopo fee maker (0,02% per lato).

Le serie giornaliere esterne entrano con **2 giorni di ritardo** (asof): il dato del giorno D
viene pubblicato dopo, usarlo lo stesso giorno sarebbe look-ahead. Ogni fonte viene inclusa solo
se copre l'intero periodo dal 2025-08-15.

Uso:
    python scripts/build_path_features.py
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PATHS = ROOT / "paths"
EXTERNAL = DATA / "external"
OUT = DATA / "path_judge_dataset.parquet"

STEP = {"1h": 60, "4h": 240}
MAKER = 0.0002
LONG, SHORT = 0.60, 0.40
PERIOD_START = pd.Timestamp("2025-08-15", tz="UTC")
LOCKBOX_START = pd.Timestamp("2026-07-24", tz="UTC")
MIN_HISTORY = 220


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = frame["close"].shift(1)
    tr = pd.concat([frame["high"] - frame["low"], (frame["high"] - prev).abs(),
                    (frame["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def prepare_candles(symbol: str, tf: str) -> pd.DataFrame:
    frame = pd.read_parquet(DATA / f"{symbol}_{tf}.parquet").sort_values("open_time")
    frame = frame.iloc[:-1].reset_index(drop=True)
    log_ret = np.log(frame["close"]).diff()
    frame["vol_24"] = log_ret.rolling(24).std()
    frame["vol_96"] = log_ret.rolling(96).std()
    frame["range_24"] = (frame["high"].rolling(24).max()
                         - frame["low"].rolling(24).min()) / frame["close"]
    frame["range_96"] = (frame["high"].rolling(96).max()
                         - frame["low"].rolling(96).min()) / frame["close"]
    frame["volume_rel_24h"] = frame["volume"] / frame["volume"].rolling(24).mean()
    frame["volume_rel_7d"] = frame["volume"] / frame["volume"].rolling(168).mean()
    frame["px_vs_ema50"] = frame["close"] / ema(frame["close"], 50) - 1
    frame["px_vs_ema200"] = frame["close"] / ema(frame["close"], 200) - 1
    frame["ema50_vs_ema200"] = ema(frame["close"], 50) / ema(frame["close"], 200) - 1
    frame["rsi14"] = rsi(frame["close"])
    frame["atr14"] = atr(frame) / frame["close"]
    frame["ret_24"] = frame["close"] / frame["close"].shift(24) - 1
    return frame


def load_funding(symbol: str) -> pd.DataFrame:
    path = DATA / "deriv" / f"{symbol}_funding.parquet"
    return pd.read_parquet(path).sort_values("funding_time") if path.is_file() else pd.DataFrame()


def external_frame() -> tuple[pd.DataFrame, list[str]]:
    """Serie giornaliere esterne, già ritardate di 2 giorni. Restituisce anche l'elenco usato."""
    pieces, used = [], []
    specs = {
        "btc_onchain": ["btc_netflow_pct"],
        "eth_onchain": ["eth_netflow_pct"],
        "stablecoins": ["stable_change_7d"],
        "ndx": ["ndx_ret_1d", "ndx_ret_5d"],
        "dxy": ["dxy_ret_1d", "dxy_ret_5d"],
    }
    for name, columns in specs.items():
        path = EXTERNAL / f"{name}.parquet"
        if not path.is_file():
            continue
        frame = pd.read_parquet(path).sort_values("date").copy()
        # Coin Metrics restituisce stringhe: si converte tutto tranne la data
        for column in frame.columns:
            if column != "date":
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame["date"].min() > PERIOD_START:
            continue                                    # non copre il periodo: esclusa
        if name in ("btc_onchain", "eth_onchain"):
            inflow = frame["FlowInExUSD"]
            outflow = frame["FlowOutExUSD"]
            frame["btc_netflow_pct" if name.startswith("btc") else "eth_netflow_pct"] = \
                (inflow - outflow) / (inflow + outflow).replace(0, np.nan)
        if name == "stablecoins":
            frame["stable_change_7d"] = frame["stablecoin_usd"].pct_change(7)
        if name in ("ndx", "dxy"):
            column = "ndx" if name == "ndx" else "dxy"
            frame[f"{column}_ret_1d"] = frame[column].pct_change()
            frame[f"{column}_ret_5d"] = frame[column].pct_change(5)
        keep = ["date"] + [c for c in columns if c in frame.columns]
        if len(keep) == 1:
            continue
        pieces.append(frame[keep])
        used.extend(keep[1:])
    if not pieces:
        return pd.DataFrame(columns=["date"]), []
    merged = pieces[0]
    for piece in pieces[1:]:
        merged = merged.merge(piece, on="date", how="outer")
    merged = merged.sort_values("date")
    # ritardo di 2 giorni: la serie di oggi si conosce dopodomani
    merged["date"] = merged["date"] + pd.Timedelta(days=2)
    return merged.ffill(), used


def path_features(paths: np.ndarray, last: float) -> dict:
    """Statistiche aggregate sui 30 path di un forecast."""
    finals = paths[:, -1] / last - 1
    return {
        "path_final_std": float(np.std(finals)),
        "path_final_skew": float(pd.Series(finals).skew()),
        "path_final_p10": float(np.percentile(finals, 10)),
        "path_final_p90": float(np.percentile(finals, 90)),
        "path_up_share": float((finals > 0).mean()),
        "path_agreement_step1": float((paths[:, 0] > last).mean()),
        "path_maxdd_median": float(np.median(
            (np.maximum.accumulate(paths, axis=1) - paths) / np.maximum.accumulate(paths, axis=1))),
        "path_vol_median": float(np.median(np.std(np.diff(np.log(paths), axis=1), axis=1))),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--tfs", nargs="*", default=None,
                        help="timeframe da includere (default: tutti quelli presenti)")
    args = parser.parse_args(argv)

    external, external_used = external_frame()
    rows: list[dict] = []

    for series_dir in sorted(glob.glob(str(PATHS / "*_*"))):
        directory = Path(series_dir)
        if not (directory / "meta.jsonl").is_file():
            continue
        symbol, tf = directory.name.split("_", 1)
        if tf not in STEP:
            continue
        if args.tfs and tf not in args.tfs:
            continue
        metas = [json.loads(line) for line in directory.joinpath("meta.jsonl").read_text().splitlines()
                 if line.strip()]
        shards = sorted(directory.glob("paths_*.npz"))
        all_paths = np.concatenate([np.load(shard)["paths"] for shard in shards]) if shards else None
        if all_paths is None or len(all_paths) != len(metas):
            print(json.dumps({"skip": directory.name, "shards": len(shards),
                              "metas": len(metas)}))
            continue

        candles = prepare_candles(symbol, tf)
        times = candles["open_time"]
        funding = load_funding(symbol)
        step = pd.Timedelta(minutes=STEP[tf])

        for meta, paths in zip(metas, all_paths):
            prob_up = float(meta["prob_up"])
            if SHORT < prob_up < LONG:
                continue
            anchor = pd.Timestamp(meta["anchor"])
            idx_candidates = candles.index[times <= anchor]
            if len(idx_candidates) == 0:
                continue
            idx = int(idx_candidates[-1])
            if idx < MIN_HISTORY:
                continue
            candle = candles.iloc[idx]
            last = float(meta["last_price"])
            horizon = int(meta["horizon"])
            realized = candle.iloc[0:0]  # segnaposto per chiarezza
            future = candles["close"].iloc[idx + 1: idx + 1 + horizon].to_numpy()
            if len(future) != horizon:
                continue
            realized_final = float(future[-1])

            funding_rate = funding_mean3 = np.nan
            if not funding.empty:
                known = funding[funding["funding_time"] <= anchor + step]
                if len(known):
                    funding_rate = float(known["funding_rate"].iloc[-1])
                    funding_mean3 = float(known["funding_rate"].iloc[-3:].mean())

            ext = {}
            if not external.empty:
                match = external[external["date"] <= anchor]
                if len(match):
                    last_row = match.iloc[-1]
                    ext = {column: float(last_row[column]) for column in external_used
                           if pd.notna(last_row[column])}

            direction = 1.0 if prob_up >= LONG else -1.0
            gross = direction * (realized_final / last - 1)
            net = gross - 2 * MAKER

            bands = {k: v for k, v in meta["bands"].items()}
            row = {
                "anchor": anchor, "symbol": symbol, "tf": tf, "horizon": horizon,
                "hour": anchor.hour, "weekday": anchor.weekday(),
                "direction": direction,
                # Kronos
                "prob_up": prob_up,
                "median_ret": float(meta["median_final"]) / last - 1,
                "band80": (bands["p90"][-1] - bands["p10"][-1]) / last,
                "band50": (bands["p75"][-1] - bands["p25"][-1]) / last,
                "band80_step1": (bands["p90"][0] - bands["p10"][0]) / last,
                "skew_band": (bands["p90"][-1] - bands["p50"][-1])
                / max(bands["p50"][-1] - bands["p10"][-1], 1e-9),
                # contesto di mercato noto
                "vol_24": float(candle["vol_24"]), "vol_96": float(candle["vol_96"]),
                "range_24": float(candle["range_24"]), "range_96": float(candle["range_96"]),
                "volume_rel_24h": float(candle["volume_rel_24h"]),
                "volume_rel_7d": float(candle["volume_rel_7d"]),
                "px_vs_ema50": float(candle["px_vs_ema50"]),
                "px_vs_ema200": float(candle["px_vs_ema200"]),
                "ema50_vs_ema200": float(candle["ema50_vs_ema200"]),
                "rsi14": float(candle["rsi14"]), "atr14": float(candle["atr14"]),
                "ret_24": float(candle["ret_24"]),
                "funding_rate": funding_rate, "funding_mean3": funding_mean3,
                # esiti
                "gross_return": gross, "net_return_maker": net,
                "target": int(net > 0),
                "realized_final": realized_final, "last_price": last,
            }
            row.update(path_features(paths, last))
            row.update(ext)
            rows.append(row)

    frame = pd.DataFrame(rows).sort_values("anchor").reset_index(drop=True)
    frame["is_lockbox"] = frame["anchor"] >= LOCKBOX_START
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.out, index=False)
    report = {
        "rows": int(len(frame)),
        "series": int(frame.groupby(["symbol", "tf"]).ngroups),
        "base_rate": round(float(frame["target"].mean()), 4),
        "from": str(frame["anchor"].min()), "to": str(frame["anchor"].max()),
        "lockbox_rows": int(frame["is_lockbox"].sum()),
        "external_used": external_used,
        "external_coverage": {c: round(float(frame[c].notna().mean()), 3)
                              for c in external_used if c in frame.columns},
        "out": args.out,
    }
    (Path(args.out).parent / "path_judge_dataset.report.json").write_text(
        json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
