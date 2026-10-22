# Fase 3 — piano di valutazione (aggiornato, da eseguire dopo il "go" sul pod)

Obiettivo: capire se Kronos batte i baseline **dopo le fee**, misurando calibrazione e
capacità direzionale su dati mai visti. Nessun tuning sul test set.

## Varianti (3, una per pod)

| ordine | id | modello | contesto | dati | note |
|---|---|---|---|---|---|
| 1 | `small512` | Kronos-small | 512 | 1h, 4h, **5m, 15m** | primo pod; risultati prima di proseguire |
| 2 | `base512` | Kronos-base | 512 | 1h, 4h | 4× parametri, ~4× costo |
| 3 | `small256` | Kronos-small | 256 | 1h, 4h | metà contesto |

**Regola di avanzamento:** dopo `small512` mi fermo, mando i risultati e aspetto l'ok
esplicito di Sam per gli altri due. Un pod per variante, mai due insieme.

## Campionamento (uguale per tutte le varianti)

- Test set: **ultimi 12 mesi**, mai usati per training né per scegliere soglie.
- Un forecast **al giorno** per serie, all'ora `H = hash(seed fisso, serie, data) % ore_giorno`,
  **stessa ora per tutte le varianti**: le tre varianti vedono esattamente le stesse candele
  e non si misura sempre la stessa fascia di mercato.
- Serie principali (1h, 4h): 5 asset × 2 tf × 365 giorni = **3.650 forecast**; orizzonte
  24 candele per 1h e 6 per 4h (= 24 h di mercato), **30 path**.
- Short-term (solo `small512`): **5m e 15m**, 5 asset × 2 tf × 365 = 3.650 forecast,
  orizzonte **12 candele** (5m → 1 h, 15m → 3 h), **30 path**. Per questi timeframe i dati
  Binance coprono solo gli ultimi 24 mesi (contesto + test).

## Checkpoint e ripresa

- Ogni forecast completato viene appeso subito a `results/<variant>/<tf>_<symbol>.jsonl`
  (data, ora scelta, bande per step, mediana, prob_up, path finali).
- Un `state.json` per serie tiene l'indice dell'ultimo giorno completato: al riavvio si
  riparte da lì e i forecast già fatti si saltano.
- Il VPS **tira** i risultati dal pod ogni 10 minuti (`rsync` via SSH dal VPS verso il pod:
  nessuna chiave del VPS finisce sul pod). Se il pod muore, i dati sincronizzati restano e
  la ripresa parte dal punto di stop su un pod nuovo.

## Backtest: due scenari di fee

| scenario | fee | uso |
|---|---|---|
| **principale** | 0,1% per lato (Bybit EU **spot**) | caso realistico |
| alternativo | futures: 0,02% maker / 0,05% taker | capire quanto pesano le fee |

Slippage: 1 tick medio per lato, dichiarato nel report. Segnali: long se `prob_up ≥ 0,6`,
short se `prob_up ≤ 0,4`, flat in mezzo (soglie **fissate prima**, nessun tuning sul test).

## Metriche

- Direzionale della mediana a orizzonte 1, 6, 24 candele.
- Calibrazione: quota di esiti dentro banda 50% e 80% (atteso ≈50% / ≈80%).
- CRPS (o pinball), MAE della mediana.
- Baseline: random walk, drift semplice, cono di volatilità storica.
- Strategia paper: ritorno totale, Sharpe, max drawdown, numero di trade, contro buy-and-hold,
  **per entrambi gli scenari di fee**.
- Verdetto in linguaggio semplice per primo ("batte il random walk dopo le fee?"), tabella
  sotto. Revisione Opus del codice di valutazione prima di chiudere la fase.

## Regola anti-leakage

Ogni forecast a T usa solo candele con `open_time + durata <= T` (l'ultima barra aperta
viene scartata dal loader). Le soglie sono fissate prima e riportate; nessuna scelta fatta
guardando il test.

## GPU e preventivo (da confermare col test di 5 minuti)

- RunPod RTX 4090 24 GB, ~€0,35–0,45/h; auto-terminate **3 h** per pod; test di 5 minuti
  prima del run pieno; messaggi Telegram a creazione e distruzione con costo; pesi e
  risultati scaricati, poi pod distrutto.
- Stima aggiornata (da calibrare col test):
  - `small512` (1h/4h + 5m/15m) ≈ **1,5–3 h** → 1 pod (se sfora le 3 h, secondo pod con
    ripresa dal checkpoint).
  - `base512` ≈ **2–3 h** → 1 pod. `small256` ≈ **1 h** → 1 pod.
  - Totale Fase 3: **€2–5**. Fase 4 (fine-tune Small): €3–5.
- **Tetto rigido €30** per Fase 3 + Fase 4. Se un run sta per sforarlo mi fermo e chiedo.

## Cosa NON faccio senza il tuo ok

Nessun pod viene creato finché non me lo dici. Dopo `small512` mi fermo comunque, anche se
i numeri sono buoni.
