#!/usr/bin/env python3
"""Riporta i risultati alla finestra canonica: esattamente 365 giorni per serie.

Serve perché prima del fix `plan_days` usava una finestra inclusiva ai due estremi: certe
serie producevano 366 giorni di calendario invece di 365 (il giorno più vecchio in più).
Qui si tiene l'insieme dei **365 giorni più recenti** per ogni file, così tutte le varianti
(Small-512, Base-512, Small-256) coprono esattamente le stesse date.

Uso:
    python scripts/prune_window.py --variant small512 --dry-run
    python scripts/prune_window.py --variant small512
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
KEEP_DAYS = 365


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", default="small512")
    parser.add_argument("--days", type=int, default=KEEP_DAYS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    for path in sorted((RESULTS / args.variant).glob("*.jsonl")):
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        if not rows:
            continue
        days = sorted({row["anchor"][:10] for row in rows})
        keep = set(days[-args.days:])
        kept = [row for row in rows if row["anchor"][:10] in keep]
        dropped = len(rows) - len(kept)
        status = "dry-run" if args.dry_run else "scritto"
        print(f"{path.name:24s} righe {len(rows):4d} giorni {len(days):3d} "
              f"tenute {len(kept):4d} (tolte {dropped}) [{status}]")
        if not args.dry_run and dropped:
            path.write_text("".join(json.dumps(row) + "\n" for row in kept), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
