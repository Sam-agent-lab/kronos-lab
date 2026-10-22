#!/usr/bin/env bash
# Tabella tempo/RAM per 1, 30, 100 campioni: un processo per misura, così il picco
# RSS è davvero quello di quel run e non il massimo cumulativo.
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p out
: > out/bench_samples.jsonl
for samples in 1 30 100; do
  echo "== samples=$samples" >&2
  nice -n 10 .venv/bin/python scripts/bench_samples.py --samples "$samples" \
    | tee -a out/bench_samples.jsonl
done
