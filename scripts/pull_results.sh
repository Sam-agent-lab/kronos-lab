#!/usr/bin/env bash
# Tira i risultati dal pod Runpod sul VPS, ogni 10 minuti.
# Nessuna chiave del VPS finisce sul pod: il pull parte sempre da qui.
set -euo pipefail

PROJECT="/home/sam/progetti/kronos-lab"
STATE="$PROJECT/pods/small512.json"
[ -f "$STATE" ] || { echo "stato pod assente: $STATE" >&2; exit 0; }

HOST=$(python3 -c "import json;print(json.load(open('$STATE'))['host'])")
PORT=$(python3 -c "import json;print(json.load(open('$STATE'))['port'])")
DEST="$PROJECT/results"
mkdir -p "$DEST"

rsync -az --timeout=120 -e "ssh -p $PORT -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20" \
    "root@$HOST:/workspace/kronos-lab/results/" "$DEST/" || {
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) pull fallito (pod spento o rete)" >&2
        exit 0
    }
FILES=$(find "$DEST" -name '*.jsonl' | wc -l)
ROWS=$(cat "$DEST"/*/*.jsonl 2>/dev/null | wc -l || echo 0)
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) pulled files=$FILES rows=$ROWS"
