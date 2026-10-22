#!/usr/bin/env bash
# Aspetta che il run sul pod finisca, poi tira i risultati e lancia il backtest.
# Pensato per girare in background sul VPS con notifica a fine corsa.
set -uo pipefail

PROJECT="/home/sam/progetti/kronos-lab"
STATE="$PROJECT/pods/small512.json"
VARIANT="${1:-small512}"
HOST=$(python3 -c "import json;print(json.load(open('$STATE'))['host'])")
PORT=$(python3 -c "import json;print(json.load(open('$STATE'))['port'])")
SSH="ssh -p $PORT -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 -o BatchMode=yes"

while true; do
    running=$($SSH "root@$HOST" 'pgrep -c -f "python scripts/evaluate.py" || true' 2>/dev/null | tr -d '[:space:]')
    if [ -z "$running" ]; then
        sleep 30   # rete instabile: un secondo tentativo prima di dichiarare finito
        running=$($SSH "root@$HOST" 'pgrep -c -f "python scripts/evaluate.py" || true' 2>/dev/null | tr -d '[:space:]')
    fi
    if [ "${running:-0}" = "0" ]; then
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) run terminato sul pod"
        break
    fi
    sleep 120
done

bash "$PROJECT/scripts/pull_results.sh"
cd "$PROJECT" || exit 1
.venv/bin/python scripts/backtest.py --variant "$VARIANT"
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) fine"
