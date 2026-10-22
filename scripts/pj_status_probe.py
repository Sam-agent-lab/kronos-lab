#!/usr/bin/env python3
"""Sonda di stato da eseguire SUL POD: stampa un JSON con i numeri del run."""

from __future__ import annotations

import glob
import json
import os
import subprocess


def sh(command: str) -> str:
    try:
        return subprocess.run(command, shell=True, capture_output=True, text=True,
                              timeout=15).stdout.strip()
    except Exception:
        return ""


rows = 0
for path in glob.glob("paths/*/state.json"):
    try:
        rows += int(json.load(open(path)).get("done", 0))
    except Exception:
        continue

gpu = sh("nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader")
payload = {
    "rows": rows,
    "series_done": len(glob.glob("paths/*/DONE")),
    "series_failed": len(glob.glob("paths/*/FAILED")),
    "stop": os.path.isfile("paths/STOP"),
    "watchdog": os.path.isfile("paths/WATCHDOG_INPOD"),
    "workers": int(sh("pgrep -c -f 'python scripts/pathjudge_worker.py'") or 0),
    "gpu": gpu,
    "active": sh("ls -d paths/*/ | tr -d '/' | tr '\\n' ' '"),
    "errors": int(sh("cat paths/logs/worker_*.log 2>/dev/null | grep -c '\"event\": \"error\"'") or 0),
}
print(json.dumps(payload))
