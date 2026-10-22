#!/usr/bin/env python3
"""Costruisce il dataset del "giudice" della Fase 7-lite.

Una riga per ogni forecast **direzionale** di Kronos (prob_up ≥ 0,60 long o ≤ 0,40 short).
Target = 1 se il trade nella direzione di Kronos è profittevole **dopo le fee maker**
(0,02% per lato), altrimenti 0.

Regola d'oro: ogni feature usa solo informazione disponibile **al momento del forecast**
(candele con `open_time + durata <= ancora`, funding/OI con timestamp <= chiusura dell'ancora,
accuratezza passata calcolata solo su forecast il cui esito era già realizzato). Nessuna feature
guarda avanti.

Uso:
    python scripts/build_judge_dataset.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DERIV = DATA / "deriv"
RESULTS = ROOT / "results"
OUT = DATA / "judge_dataset.parquet"

STEP = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
MAKER = 0.0002
LONG, SHORT = 0.60, 0.40
LOCKBOX_DAYS = 90          # ultimi 3 mesi sigillati
MIN_HISTORY = 220          # candele minime per EMA200


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = frame["high"], frame["low"], frame["close"]
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def prepare_candles(symbol: str, tf: str) -> pd.DataFrame:
    path = DATA / f"{symbol}_{tf}.parquet"
    frame = pd.read_parquet(path).sort_values("open_time").reset_index(drop=True)
    frame = frame.iloc[:-1].reset_index(drop=True)      # solo candele chiuse
    log_ret = np.log(frame["close"]).diff()
    frame["vol_24"] = log_ret.rolling(24).std()
    frame["vol_96"] = log_ret.rolling(96).std()
    frame["range_24"] = ((frame["high"].rolling(24).max()
                          - frame["low"].rolling(24).min()) / frame["close"])
    frame["range_96"] = ((frame["high"].rolling(96).max()
                          - frame["low"].rolling(96).min()) / frame["close"])
    frame["vol_ma_24"] = frame["volume"].rolling(24).mean()
    frame["vol_ma_168"] = frame["volume"].rolling(168).mean()
    frame["ema50"] = ema(frame["close"], 50)
    frame["ema200"] = ema(frame["close"], 200)
    frame["rsi14"] = rsi(frame["close"])
    frame["atr14"] = atr(frame) / frame["close"]
    return frame


def load_derivatives(symbol: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    fund = pd.DataFrame()
    oi = pd.DataFrame()
    fpath = DERIV / f"{symbol}_funding.parquet"
    opath = DERIV / f"{symbol}_oi_1h.parquet"
    if fpath.is_file():
        fund = pd.read_parquet(fpath).sort_values("funding_time")
    if opath.is_file():
        oi = pd.read_parquet(opath).sort_values("open_time")
    return fund, oi


def past_accuracy(records: list[dict], tf: str) -> list[float]:
    """Accuratezza di Kronos sulle ultime previsioni della serie il cui esito era già noto."""
    step = pd.Timedelta(minutes=STEP[tf])
    values = []
    for index, record in enumerate(records):
        anchor = pd.Timestamp(record["anchor"])
        history = []
        for previous in records[:index]:
            realized_at = pd.Timestamp(previous["anchor"]) + step * previous["horizon"]
            if realized_at <= anchor:
                history.append(previous["hit_final"])
        window = history[-30:]
        values.append(float(np.mean(window)) if window else np.nan)
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", default="small512")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    rows: list[dict] = []
    for path in sorted((RESULTS / args.variant).glob("*.jsonl")):
        tf = path.name.split("_")[0]
        symbol = path.stem.split("_", 1)[1]
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                   if line.strip()]
        records = [r for r in records if len(r.get("realized", [])) == r.get("horizon")]
        records.sort(key=lambda item: item["anchor"])
        for record in records:
            record["hit_final"] = int(
                np.sign(record["bands"]["p50"][-1] - record["last_price"])
                == np.sign(record["realized"][-1] - record["last_price"]))
        accuracies = past_accuracy(records, tf)

        candles = prepare_candles(symbol, tf)
        times = candles["open_time"]
        fund, oi = load_derivatives(symbol)

        for record, past_acc in zip(records, accuracies):
            prob_up = float(record["prob_up"])
            if SHORT < prob_up < LONG:
                continue                      # nessun trade: il target non è definito
            anchor = pd.Timestamp(record["anchor"])
            position = candles.index[times <= anchor]
            if len(position) == 0:
                continue
            idx = int(position[-1])
            if idx < MIN_HISTORY:
                continue
            candle = candles.iloc[idx]
            step = pd.Timedelta(minutes=STEP[tf])
            close_at = anchor + step

            p10 = np.asarray(record["bands"]["p10"], float)
            p25 = np.asarray(record["bands"]["p25"], float)
            p50 = np.asarray(record["bands"]["p50"], float)
            p75 = np.asarray(record["bands"]["p75"], float)
            p90 = np.asarray(record["bands"]["p90"], float)
            last = float(record["last_price"])
            finals = np.asarray(record["path_final"], float)
            median_final = float(np.median(finals))

            # funding: ultimo valore noto alla chiusura dell'ancora + media ultime 3
            funding_rate = np.nan
            funding_mean3 = np.nan
            if not fund.empty:
                known = fund[fund["funding_time"] <= close_at]
                if len(known):
                    funding_rate = float(known["funding_rate"].iloc[-1])
                    funding_mean3 = float(known["funding_rate"].iloc[-3:].mean())
            # open interest: variazione 1h e 24h rispetto all'ora precedente
            oi_change_1h = np.nan
            oi_change_24h = np.nan
            if not oi.empty:
                known = oi[oi["open_time"] <= anchor]
                if len(known) >= 25:
                    current = float(known["open_interest"].iloc[-1])
                    oi_change_1h = current / float(known["open_interest"].iloc[-2]) - 1
                    oi_change_24h = current / float(known["open_interest"].iloc[-25]) - 1

            realized_final = float(record["realized"][-1])
            direction = 1.0 if prob_up >= LONG else -1.0
            gross = direction * (realized_final / last - 1)
            net_maker = gross - 2 * MAKER

            rows.append({
                "anchor": anchor, "symbol": symbol, "tf": tf,
                "weekday": anchor.weekday(), "hour": anchor.hour,
                # output Kronos
                "prob_up": prob_up,
                "median_ret": median_final / last - 1,
                "band80": float((p90[-1] - p10[-1]) / last),
                "band50": float((p75[-1] - p25[-1]) / last),
                "band80_step1": float((p90[0] - p10[0]) / last),
                "agreement": float(record["prob_up_at"].get("1", np.nan)),
                "path_skew": float((p90[-1] - p50[-1]) / max(p50[-1] - p10[-1], 1e-9)),
                "mean_vs_median": float(np.mean(finals) / last - 1),
                "regime": record.get("regime", "CHOPPY"),
                "past_acc_30": past_acc,
                # contesto di mercato noto all'ancora
                "vol_24": float(candle["vol_24"]),
                "vol_96": float(candle["vol_96"]),
                "range_24": float(candle["range_24"]),
                "range_96": float(candle["range_96"]),
                "volume_rel_24h": float(candle["volume"] / candle["vol_ma_24"])
                if candle["vol_ma_24"] > 0 else np.nan,
                "volume_rel_7d": float(candle["volume"] / candle["vol_ma_168"])
                if candle["vol_ma_168"] > 0 else np.nan,
                "px_vs_ema50": float(candle["close"] / candle["ema50"] - 1),
                "px_vs_ema200": float(candle["close"] / candle["ema200"] - 1),
                "ema50_vs_ema200": float(candle["ema50"] / candle["ema200"] - 1),
                "rsi14": float(candle["rsi14"]),
                "atr14": float(candle["atr14"]),
                # derivati
                "funding_rate": funding_rate,
                "funding_mean3": funding_mean3,
                # NON usate come feature: Binance conserva solo ~20 giorni di open interest
                # pubblico, quindi esisterebbero solo nel lockbox. Tenute per documentare.
                "oi_change_1h": oi_change_1h,
                "oi_change_24h": oi_change_24h,
                # esiti (mai usati come feature)
                "direction": direction,
                "gross_return": gross,
                "net_return_maker": net_maker,
                "target": int(net_maker > 0),
            })

    frame = pd.DataFrame(rows).sort_values("anchor").reset_index(drop=True)
    frame["is_lockbox"] = frame["anchor"] >= (frame["anchor"].max()
                                              - pd.Timedelta(days=LOCKBOX_DAYS))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.out, index=False)
    print(json.dumps({
        "rows": int(len(frame)),
        "base_rate": float(frame["target"].mean()),
        "series": int(frame.groupby(["symbol", "tf"]).ngroups),
        "lockbox_rows": int(frame["is_lockbox"].sum()),
        "lockbox_from": str(frame.loc[frame["is_lockbox"], "anchor"].min()),
        "funding_coverage": float(frame["funding_rate"].notna().mean()),
        "oi_coverage": float(frame["oi_change_1h"].notna().mean()),
        "out": args.out,
    }, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
