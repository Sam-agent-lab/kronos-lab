#!/usr/bin/env python3
"""Helper Runpod per la Fase 3: crea pod con auto-terminate, elenca, distrugge.

Regole di sicurezza codificate qui, non a memoria:
- ogni pod nasce con `terminateAfter` (secondi) obbligatorio, default 3 ore;
- prima di creare stampa il costo stimato e si ferma se il tetto di budget è superato;
- la chiave si legge da `.env` e non viene mai stampata.

Uso:
    python scripts/runpod.py list
    python scripts/runpod.py gpus --gpu "NVIDIA GeForce RTX 4090"
    python scripts/runpod.py create --name kronos-small512 --gpu "NVIDIA GeForce RTX 4090" \
        --hours 3 --price-per-hour 0.40 --budget-left 30
    python scripts/runpod.py delete <pod_id>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
API = "https://rest.runpod.io/v1"
IMAGE = "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"


def api_key() -> str:
    key = os.environ.get("RUNPOD_API_KEY")
    if key:
        return key
    if ENV.is_file():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if line.startswith("RUNPOD_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("RUNPOD_API_KEY assente (vedi .env del progetto)")


def call(method: str, path: str, **kwargs) -> tuple[int, dict | list]:
    response = requests.request(method, f"{API}{path}", timeout=60,
                                headers={"Authorization": f"Bearer {api_key()}",
                                         "Content-Type": "application/json"},
                                **kwargs)
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return response.status_code, payload


def cmd_list(_args) -> int:
    code, payload = call("GET", "/pods")
    pods = payload.get("data", payload) if isinstance(payload, dict) else payload
    if code != 200:
        print(f"errore API: HTTP {code}")
        return 1
    if not pods:
        print("pod attivi: 0 (lista vuota = ok)")
        return 0
    for pod in pods:
        print(f"{pod.get('id')} {pod.get('name')} {pod.get('desiredStatus')} "
              f"{pod.get('costPerHr')}/h")
    print(f"totale pod: {len(pods)}")
    return 0


def cmd_gpus(args) -> int:
    code, payload = call("GET", "/gpus")
    if code != 200:
        print(f"errore API: HTTP {code}")
        return 1
    rows = payload.get("data", payload) if isinstance(payload, dict) else payload
    wanted = (args.gpu or "").lower()
    for row in rows:
        name = str(row.get("displayName") or row.get("id") or "")
        if wanted and wanted not in name.lower():
            continue
        print(f"{name} | {row.get('memoryInGb')} GB | {row.get('communityPrice') or row.get('securePrice')}/h")
    return 0


def cmd_create(args) -> int:
    hours = args.hours
    estimate = hours * args.price_per_hour
    if estimate > args.budget_left:
        print(f"STOP: stima {estimate:.2f} € > budget residuo {args.budget_left:.2f} €")
        return 2
    terminate_at = datetime.now(timezone.utc) + timedelta(hours=hours)
    body = {
        "name": args.name,
        "imageName": IMAGE,
        "gpuTypeIds": [args.gpu],
        "gpuCount": 1,
        "containerDiskInGb": args.disk,
        "volumeInGb": 0,
        "ports": "22/tcp,8888/http",
        "env": [
            {"key": "JUPYTER_PASSWORD", "value": "kronos"},
            {"key": "PUBLIC_KEY", "value": _public_key()},
        ],
        "dockerArgs": "sleep infinity",
        # auto-terminate: Runpod non ha un campo API universale, quindi il pod
        # si spegne da sé con un watchdog lanciato all'avvio (vedi docs/runpod.md)
        "terminateAfter": None,
    }
    body.pop("terminateAfter")
    code, payload = call("POST", "/pods", json=body)
    if code not in (200, 201):
        print(f"errore creazione: HTTP {code} {json.dumps(payload)[:300]}")
        return 1
    pod_id = payload.get("data", payload).get("id") if isinstance(payload, dict) else None
    print(json.dumps({"pod_id": pod_id, "name": args.name,
                      "auto_terminate_utc": terminate_at.isoformat(),
                      "estimate_eur": round(estimate, 2)}, indent=1))
    return 0


def _public_key() -> str:
    for name in ("id_ed25519.pub", "id_rsa.pub"):
        path = Path.home() / ".ssh" / name
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    return ""


def cmd_delete(args) -> int:
    code, payload = call("DELETE", f"/pods/{args.pod_id}")
    print(f"delete {args.pod_id}: HTTP {code}")
    return 0 if code in (200, 204) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="helper Runpod (Fase 3)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list").set_defaults(func=cmd_list)
    gpus = sub.add_parser("gpus")
    gpus.add_argument("--gpu")
    gpus.set_defaults(func=cmd_gpus)
    create = sub.add_parser("create")
    create.add_argument("--name", required=True)
    create.add_argument("--gpu", default="NVIDIA GeForce RTX 4090")
    create.add_argument("--hours", type=float, default=3.0)
    create.add_argument("--price-per-hour", type=float, default=0.40)
    create.add_argument("--budget-left", type=float, default=30.0)
    create.add_argument("--disk", type=int, default=50)
    create.set_defaults(func=cmd_create)
    delete = sub.add_parser("delete")
    delete.add_argument("pod_id")
    delete.set_defaults(func=cmd_delete)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
