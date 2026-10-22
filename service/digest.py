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
    stamp = max(row["generated_at"] for row in rows).replace("T", " ")[:16]
    lines = [f"Kronos digest · {stamp} UTC"]
    for row in rows:
        arrow = "▲" if row["prob_up"] >= 0.5 else "▼"
        median = row["median_final"]
        # prezzi da 1 a 100.000: 5 cifre significative, mai "mediana 1"
        shown = f"{median:,.2f}" if median < 100 else f"{median:,.1f}" if median < 1000 else f"{median:,.0f}"
        lines.append(
            f"{row['symbol']} {row['tf']}: {row['regime']} {arrow} "
            f"prob_up={row['prob_up']:.2f} · mediana {shown} "
            f"({(median / row['last_price'] - 1) * 100:+.2f}%) · "
            f"banda 10-90 {row['band_width_pct']['p10_p90']:.2f}% · "
            f"{row['samples']} path"
        )
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
