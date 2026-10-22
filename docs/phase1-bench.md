# Fase 1 — tempo e RAM per numero di campioni

BTCUSDT 1h, orizzonte 24 candele, Kronos-small, CPU (6 vCPU, `nice -n 10`), un processo per misura.

| campioni | inferenza (s) | s/campione | picco RAM (MB) |
|---|---|---|---|
| 1 | 11.4 | 11.37 | 524 |
| 30 | 359.1 | 11.97 | 2026 |
| 100 | 1767.4 | 17.67 | 4080 |

Picco RAM misurato con `getrusage(RUSAGE_SELF).ru_maxrss` del processo che fa l'inferenza (include il modello in memoria).
