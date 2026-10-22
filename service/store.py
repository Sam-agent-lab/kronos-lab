"""SQLite: una riga per forecast, così la Fase 3 e la dashboard possono valutarla.

Nessun dato personale, nessuna chiave: solo previsioni e metadati.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "var" / "forecasts.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TEXT NOT NULL,
    last_candle TEXT NOT NULL,
    symbol TEXT NOT NULL,
    tf TEXT NOT NULL,
    model TEXT NOT NULL,
    context INTEGER NOT NULL,
    samples INTEGER NOT NULL,
    horizon INTEGER NOT NULL,
    last_price REAL NOT NULL,
    median_final REAL NOT NULL,
    prob_up REAL NOT NULL,
    regime TEXT NOT NULL,
    p10 REAL NOT NULL, p25 REAL NOT NULL, p50 REAL NOT NULL,
    p75 REAL NOT NULL, p90 REAL NOT NULL,
    band_p10_p90_pct REAL NOT NULL,
    band_p25_p75_pct REAL NOT NULL,
    seconds REAL NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE(symbol, tf, model, context, last_candle)
);
CREATE INDEX IF NOT EXISTS idx_forecasts_lookup ON forecasts(symbol, tf, generated_at);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    connection.executescript(SCHEMA)
    return connection


def save(record: dict, path: Path | None = None) -> bool:
    """Inserisce il forecast; False se quella candela era già registrata."""
    with connect(path) as connection:
        try:
            connection.execute(
                """INSERT INTO forecasts (generated_at, last_candle, symbol, tf, model,
                    context, samples, horizon, last_price, median_final, prob_up, regime,
                    p10, p25, p50, p75, p90, band_p10_p90_pct, band_p25_p75_pct, seconds,
                    payload) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record["generated_at"], record["last_candle"], record["symbol"],
                    record["tf"], record["model"], record["context"], record["samples"],
                    record["horizon"], record["last_price"], record["median_final"],
                    record["prob_up"], record["regime"],
                    record["bands_final"]["p10"], record["bands_final"]["p25"],
                    record["bands_final"]["p50"], record["bands_final"]["p75"],
                    record["bands_final"]["p90"],
                    record["band_width_pct"]["p10_p90"], record["band_width_pct"]["p25_p75"],
                    record["seconds"], json.dumps(record),
                ),
            )
        except sqlite3.IntegrityError:
            return False
    return True


def latest(limit: int = 20, path: Path | None = None) -> list[dict]:
    with connect(path) as connection:
        rows = connection.execute(
            """SELECT symbol, tf, generated_at, regime, prob_up, median_final, last_price,
                      band_p10_p90_pct, seconds
               FROM forecasts ORDER BY generated_at DESC LIMIT ?""", (limit,)
        ).fetchall()
    keys = ["symbol", "tf", "generated_at", "regime", "prob_up", "median_final",
            "last_price", "band_p10_p90_pct", "seconds"]
    return [dict(zip(keys, row, strict=True)) for row in rows]


def latest_per_series(path: Path | None = None) -> list[dict]:
    with connect(path) as connection:
        cursor = connection.execute(
            """SELECT f.* FROM forecasts f
               JOIN (SELECT symbol, tf, MAX(generated_at) AS ts FROM forecasts
                     GROUP BY symbol, tf) latest
                 ON f.symbol = latest.symbol AND f.tf = latest.tf AND f.generated_at = latest.ts
               ORDER BY f.symbol, f.tf"""
        )
        columns = [description[0] for description in cursor.description or []]
        rows = cursor.fetchall()
    return [dict(zip(columns, row, strict=True)) for row in rows]
