"""Digest Telegram: una riga per asset, letta dalla cache dello scheduler.

Stampato su stdout e consegnato da un cronjob Hermes in modalità no_agent: nessun
LLM, nessuna chiamata esterna, solo i numeri dell'ultimo forecast.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "var" / "cache"


def main() -> int:
    rows = []
    for path in sorted(CACHE.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows.append(payload)
    if not rows:
        print("Kronos: nessun forecast in cache (scheduler mai eseguito).")
        return 0

    rows.sort(key=lambda row: (row["symbol"], row["tf"]))
    lines = [f"Kronos digest · {rows[0]['generated_at'][:16].replace('T', ' ')} UTC"]
    for row in rows:
        arrow = "▲" if row["prob_up"] >= 0.5 else "▼"
        lines.append(
            f"{row['symbol']} {row['tf']}: {row['regime']} {arrow} "
            f"prob_up={row['prob_up']:.2f} · mediana {row['median_final']:,.0f} "
            f"({(row['median_final'] / row['last_price'] - 1) * 100:+.2f}%) · "
            f"banda 10-90 {row['band_width_pct']['p10_p90']:.2f}% · "
            f"{row['samples']} path"
        )
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
