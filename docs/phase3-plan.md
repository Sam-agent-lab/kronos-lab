# Fase 3 — piano di valutazione (bozza da approvare prima del pod)

Obiettivo: capire se Kronos batte i baseline dopo le fee, misurando calibrazione e
capacità direzionale su dati **mai visti**. Nessun tuning sul test set.

## Varianti da valutare (3, come chiesto da Sam)

| id | modello | contesto | note |
|---|---|---|---|
| `small512` | NeoQuasar/Kronos-small | 512 | default |
| `base512` | NeoQuasar/Kronos-base | 512 | 4× parametri, costa ~4× |
| `small256` | NeoQuasar/Kronos-small | 256 | stessa famiglia, metà contesto |

## Periodo e campionamento

- Test set: **ultimi 12 mesi** (mai usati per training né per scegliere soglie).
- Un forecast **al giorno** per serie (5 asset × 2 timeframe = 10 serie → 3.650 forecast).
- L'ora del forecast è **casuale ma con seed fisso**, e la stessa per tutti i modelli:
  `hour = hash(seed, serie, data) % 24`, poi si usa la prima candela chiusa a
  quell'ora. Così non si misura sempre la stessa fascia di mercato.
- Orizzonte: 24 candele per 1h (24 h), 6 candele per 4h (24 h) — confrontabili.
- Path: **30** per i punti valutati (più path = bande più stabili; 3.650 × 30 = 109.500
  path, ~6 h su una 4090). Se il tempo stringe, si scende a 20 path dichiarandolo.

## Metriche

- Accuratezza direzionale della **mediana** a orizzonte 1, 6, 24.
- Calibrazione: quota di esiti dentro la banda 50% e 80% (atteso ≈50% e ≈80%).
- CRPS (o pinball loss) sulla distribuzione; MAE della mediana.
- Baseline: random walk (ultimo prezzo), drift semplice, cono di volatilità storica.
- Strategia paper: long/short/flat da soglie su `prob_up`, **fee 0,1% per lato + slippage**;
  totale ritorno, Sharpe, max drawdown, numero di trade, contro buy-and-hold.

## Regola anti-leakage

Ogni forecast a T usa solo candele con `open_time + durata <= T` (l'ultima barra aperta
viene scartata dal loader). Nessuna soglia viene scelta guardando il test: le soglie
(es. 0,6 / 0,4) sono fissate **prima** e riportate nel report, oppure si riporta la curva
completa delle soglie dichiarando che è esplorativa.

## GPU

- RunPod RTX 4090 24 GB, ~€0,35–0,45/h; auto-terminate a 3 h; test di 5 minuti prima del
  run completo; messaggi Telegram a creazione e distruzione con costo; pesi e risultati
  scaricati sul VPS, poi pod distrutto subito.
- Stima: **4–6 h ≈ €2–4** per la Fase 3. Budget totale Fase 3+4: **€30**.
- **Nessun pod viene creato senza conferma esplicita di Sam.**
