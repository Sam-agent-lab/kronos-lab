#!/usr/bin/env bash
# Tira i path generati dal pod sul VPS, ogni 10 minuti (o a richiesta).
set -euo pipefail

PROJECT="/home/sam/progetti/kronos-lab"
STATE="$PROJECT/pods/pathjudge.json"
[ -f "$STATE" ] || { echo "stato pod assente" >&2; exit 0; }

HOST=$(python3 -c "import json;print(json.load(open('$STATE'))['host'])")
PORT=$(python3 -c "import json;print(json.load(open('$STATE'))['port'])")
mkdir -p "$PROJECT/paths"

rsync -az --timeout=180 -e "ssh -p $PORT -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20" \
    "root@$HOST:/workspace/kronos-lab/paths/" "$PROJECT/paths/" || {
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) pull fallito (pod spento o rete)" >&2
        exit 0
    }
SHARDS=$(find "$PROJECT/paths" -name 'paths_*.npz' | wc -l)
ROWS=$(cat "$PROJECT/paths"/*/meta.jsonl 2>/dev/null | wc -l || echo 0)
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) pulled shards=$SHARDS rows=$ROWS"
