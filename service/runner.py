"""Scheduler: precalcola il forecast appena una candela è chiusa, salva cache e DB.

Lo lancia un timer systemd ogni 10 minuti: per ogni serie controlla l'ultima candela
chiusa e calcola solo se è nuova rispetto alla cache. Così non si spreca CPU e il
servizio risponde sempre con l'ultimo dato disponibile.

Uso: python service/runner.py [--once] [--symbol BTCUSDT] [--tf 1h]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))
sys.path.insert(0, str(ROOT / "scripts"))

import core  # noqa: E402
import store  # noqa: E402

CACHE = ROOT / "var" / "cache"
LOG = ROOT / "var" / "runner.log"


def log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def newest_closed(symbol: str, tf: str) -> str:
    candles = core.load_closed(symbol, tf, lookback=8)
    return str(candles["open_time"].iloc[-1])


def run_series(symbol: str, tf: str, samples: int) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE / f"{symbol}_{tf}.json"
    newest = newest_closed(symbol, tf)
    if cache_path.is_file():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("last_candle") == newest:
            return "skip"
    payload = core.forecast(symbol, tf, samples=samples)
    cache_path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    store.save(payload)
    return f"ok {payload['seconds']}s {payload['regime']} prob_up={payload['prob_up']}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="un giro e basta")
    parser.add_argument("--symbol")
    parser.add_argument("--tf")
    parser.add_argument("--samples", type=int, default=core.DEFAULT_SAMPLES)
    args = parser.parse_args(argv)

    symbols = [args.symbol.upper()] if args.symbol else core.SYMBOLS
    timeframes = [args.tf] if args.tf else core.TIMEFRAMES
    for symbol in symbols:
        for tf in timeframes:
            try:
                result = run_series(symbol, tf, args.samples)
            except Exception as exc:  # non fermare il ciclo per una serie
                log(f"{symbol} {tf} ERROR {type(exc).__name__}: {exc}")
                continue
            log(f"{symbol} {tf} {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
