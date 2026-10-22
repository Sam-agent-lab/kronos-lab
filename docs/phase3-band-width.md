# Fase 3 — larghezza bande vs volatilità realizzata

Campione: **7296** forecast (small512), serie 20, una previsione al giorno.

Grandezze confrontate sullo stesso orizzonte: banda prevista (p90−p10)/prezzo,
range realizzato (max−min)/prezzo, baseline storica = range delle N candele
precedenti l'ancora (N = orizzonte).

## In pool (tutte le serie)

| misura | Pearson | Spearman |
|---|---|---|
| banda prevista vs range realizzato | 0.556 | 0.753 |
| baseline storica vs range realizzato | 0.607 | 0.750 |

Rapporto mediano realizzato/previsto: **0.67** (1,00 = banda giusta in mediana).

## Per timeframe

| tf | n | Pearson banda | Spearman banda | Pearson storica | Spearman storica |
|---|---|---|---|---|---|
| 15m | 1825 | 0.465 | 0.459 | 0.424 | 0.500 |
| 1h | 1823 | 0.240 | 0.288 | 0.415 | 0.389 |
| 4h | 1823 | 0.331 | 0.311 | 0.389 | 0.330 |
| 5m | 1825 | 0.476 | 0.566 | 0.469 | 0.596 |

## Per serie

| serie | n | Pearson banda | Spearman banda | Pearson storica | Spearman storica |
|---|---|---|---|---|---|
| BNBUSDT 15m | 365 | 0.401 | 0.392 | 0.375 | 0.415 |
| BNBUSDT 1h | 364 | 0.247 | 0.298 | 0.400 | 0.346 |
| BNBUSDT 4h | 365 | 0.207 | 0.280 | 0.384 | 0.264 |
| BNBUSDT 5m | 365 | 0.501 | 0.557 | 0.546 | 0.625 |
| BTCUSDT 15m | 365 | 0.284 | 0.321 | 0.346 | 0.434 |
| BTCUSDT 1h | 365 | 0.090 | 0.113 | 0.452 | 0.320 |
| BTCUSDT 4h | 365 | 0.241 | 0.166 | 0.343 | 0.268 |
| BTCUSDT 5m | 365 | 0.465 | 0.528 | 0.455 | 0.539 |
| ETHUSDT 15m | 365 | 0.400 | 0.454 | 0.396 | 0.464 |
| ETHUSDT 1h | 365 | 0.182 | 0.282 | 0.346 | 0.277 |
| ETHUSDT 4h | 365 | 0.164 | 0.148 | 0.205 | 0.204 |
| ETHUSDT 5m | 365 | 0.392 | 0.522 | 0.423 | 0.556 |
| SOLUSDT 15m | 365 | 0.361 | 0.421 | 0.314 | 0.459 |
| SOLUSDT 1h | 365 | 0.192 | 0.192 | 0.331 | 0.297 |
| SOLUSDT 4h | 364 | 0.320 | 0.285 | 0.335 | 0.293 |
| SOLUSDT 5m | 365 | 0.465 | 0.493 | 0.402 | 0.539 |
| XRPUSDT 15m | 365 | 0.589 | 0.464 | 0.546 | 0.556 |
| XRPUSDT 1h | 364 | 0.214 | 0.260 | 0.398 | 0.395 |
| XRPUSDT 4h | 364 | 0.378 | 0.301 | 0.481 | 0.339 |
| XRPUSDT 5m | 365 | 0.465 | 0.558 | 0.460 | 0.578 |

## Lettura dei numeri

- **La banda segue la volatilità**: in pool, correlazione di rango (Spearman) tra banda prevista
  e range realizzato **0,753**. Non è rumore.
- **Ma non aggiunge nulla alla persistenza**: il range delle N candele precedenti all'ancora
  correla **0,750**, cioè lo stesso. In Pearson la baseline storica è pure meglio (0,607 contro
  0,556). A 1h e 4h Kronos è **peggiore** della baseline (Spearman 0,288 vs 0,389 a 1h;
  0,311 vs 0,330 a 4h); a 5m e 15m sono equivalenti.
- **Calibrazione del livello, non della forma**: banda p10–p90 mediana **1,93%** del prezzo,
  range realizzato mediano **1,25%**, movimento mediano |fine−inizio| **0,65%**. La banda è
  quindi ~1,5× il range realizzato e ~2,6× il movimento tipico: **larga, non stretta**.
  Eppure il prezzo finale cade dentro la banda solo nel **52,2%** dei casi invece dell'80%.
  Il problema non è la larghezza, è il **centro**: l'errore mediano del centro (|finale − p50|)
  è **0,78%**, più grande del movimento tipico. La mediana è sistematicamente spostata, quindi
  la banda larga non copre comunque l'esito.

Conseguenza pratica: la larghezza delle bande di Kronos è utilizzabile come indicatore di
volatilità solo quanto lo è "quanto si è mosso nelle ultime N candele", e questo lo sappiamo
già senza il modello.
