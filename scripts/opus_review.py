#!/usr/bin/env python3
"""Chiamata Opus via gate del director, brief da file, risposta su file.

Uso: python scripts/opus_review.py docs/op-review-brief.md docs/op-review-verdict.md
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECTOR = Path.home() / ".hermes" / "plugins" / "director"


def load_director():
    spec = importlib.util.spec_from_file_location("director_plugin", DIRECTOR / "__init__.py")
    if spec is None or spec.loader is None:
        raise SystemExit("plugin director non caricabile")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        raise SystemExit("uso: opus_review.py <brief.md> <verdict.md>")
    brief_path = ROOT / args[0] if not Path(args[0]).is_absolute() else Path(args[0])
    out_path = ROOT / args[1] if not Path(args[1]).is_absolute() else Path(args[1])
    brief = brief_path.read_text(encoding="utf-8")
    director = load_director()
    text, code, row = director.run_claude(brief, effort="medium", kind="director")
    out_path.write_text(text, encoding="utf-8")
    print(f"exit={code} ledger={row} caratteri={len(text)}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
