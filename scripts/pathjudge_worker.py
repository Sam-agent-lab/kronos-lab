#!/usr/bin/env python3
"""Worker per la generazione "path judge": prende serie da una coda, una alla volta.

La coda è un file di task (`SYMBOL:TF`). Il claim è atomico (`mkdir` su una cartella lock),
quindi due worker non possono prendere la stessa serie; `DONE` evita di rifare una serie finita,
`FAILED` annota quelle andate male. Dopo 2 retry su una serie il worker scrive `STOP` e esce:
la regola d'oro è fermarsi, non continuare a oltranza.

Uso:
    python scripts/pathjudge_worker.py --tasks paths/tasks.txt --device cuda
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "third_party" / "kronos"))

import path_judge_generate as gen   # noqa: E402

PATHS = ROOT / "paths"
LOCKS = PATHS / "locks"
STOP = PATHS / "STOP"


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def claim(tasks: list[str]) -> str | None:
    for task in tasks:
        directory = PATHS / task.replace(":", "_")
        if (directory / "DONE").is_file() or (directory / "FAILED").is_file():
            continue
        lock = LOCKS / f"{task.replace(':', '_')}.lock"
        try:
            lock.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue
        return task
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", default=str(PATHS / "tasks.txt"))
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args(argv)

    LOCKS.mkdir(parents=True, exist_ok=True)
    tasks = [line.strip() for line in Path(args.tasks).read_text().splitlines()
             if line.strip() and not line.startswith("#")]
    predictor = gen.load_predictor(args.device)
    print(json.dumps({"event": "worker_start", "tasks": len(tasks), "at": now()}), flush=True)

    while True:
        if STOP.is_file():
            print(json.dumps({"event": "stop_file", "at": now()}), flush=True)
            return 4
        task = claim(tasks)
        if task is None:
            print(json.dumps({"event": "queue_empty", "at": now()}), flush=True)
            return 0
        symbol, tf = task.split(":")
        directory = PATHS / task.replace(":", "_")
        attempt = 0
        while True:
            attempt += 1
            print(json.dumps({"event": "start_task", "task": task,
                              "attempt": attempt, "at": now()}), flush=True)
            code = gen.run_series(predictor, symbol, tf)
            if code == 0:
                (directory / "DONE").write_text(now())
                break
            print(json.dumps({"event": "task_error", "task": task, "code": code,
                              "attempt": attempt, "at": now()}), flush=True)
            if attempt >= 2:                       # 1 tentativo + 1 retry: poi stop
                (directory / "FAILED").write_text(f"{now()} code={code}")
                STOP.write_text(f"{task} failed after {attempt} attempts at {now()}")
                return 5
            time.sleep(5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
