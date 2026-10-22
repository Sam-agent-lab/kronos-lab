# Fase 3 — risultati Small-512

Pod: NVIDIA A40 46 GB, secure cloud, EU-SE-1, $0,59/h (la RTX 4090 community US-IL-1 non aveva
istanze libere: sostituzione già approvata da Sam).
Run: `1h → 4h → 5m → 15m`, 30 path, contesto 512, una previsione al giorno per serie all'ora
pseudo-casuale `H = sha256(seed|symbol|tf|data) % slot_giornalieri` (stessa ora per tutte le
varianti). Test set: ultimi 365 giorni, mai usato per training né per soglie.

## Tempi misurati

- Test di 5 minuti: **2,06 s** per forecast (30 path, 512 di contesto, 24 candele).
- Riferimento CPU sullo stesso codice: 72–79 s con **5** path → la GPU è ~70× più veloce a
  parità di path.

## Risultati (da completare a fine run)

## Numeri: 8.650 contro 7.300, e i 365 giorni per serie

- **7.300 è il numero giusto**, ed è quello che il piano approvato diceva: 5 asset × 2 timeframe
  (1h, 4h) × 365 = **3.650**, più 5 asset × 2 timeframe (5m, 15m) × 365 = **3.650** → 7.300
  forecast su **20 serie**.
- **8.650 era un errore mio di somma** in un messaggio di stato: ho sommato i blocchi a mente
  invece di rifare il conto. Il perimetro non è cambiato: nessun timeframe o asset è stato
  aggiunto o tolto.
- **365 giorni per serie**: la prima versione di `plan_days` costruiva la finestra in modo
  inclusivo ai due estremi, quindi alcune serie uscivano con 366 giorni di calendario (un giorno
  in più, il più vecchio). Verificato con `prune_window.py --dry-run`: 1h e 4h hanno già
  **365 righe / 365 giorni distinti / 0 duplicati**; 5m e 15m ne avevano 366. Corretto il codice
  (`days[-365:]`, finestra canonica identica per ogni serie e ogni variante) e a fine run il
  giorno in più viene rimosso con `scripts/prune_window.py`, così tutte le varianti coprono
  esattamente le stesse date.

| timeframe | serie | forecast | direzione a fine orizzonte | copertura banda 80% |
|---|---|---|---|---|
| 1h | 5 | 1.823 | 50,0% | 45,9% |
| 4h | 5 | 1.823 | 51,5% | 55,8% |
| 5m | 5 | 1.825 | 51,5% | 51,0% |
| 15m | 5 | 1.825 | 51,6% | 56,2% |
| **totale** | **20** | **7.296** | **51,2%** | **52,2%** |

- Direzione della mediana: 1 candela **50,5%**, metà orizzonte **49,7%**, fine **51,2%**.
- Calibrazione: dentro la banda 50% **30,5%** (atteso 50%), dentro la 80% **52,2%** (atteso 80%):
  bande troppo strette, il modello è sovraconfidente.
- MAE della mediana **1,60%**; pinball medio 82,6 (unità di prezzo, confrontabile solo fra varianti).
- Segnali generati: **5.906** su 7.296 giorni (80,9%), long 2.427 / short 3.479, win rate **40,2%**.

Strategia paper (equity su 12 mesi, un conto, peso uguale per giorno):

| scenario fee | equity finale | max drawdown | media per trade |
|---|---|---|---|
| nessuna fee (solo modello) | **0,922x** | — | −0,026% |
| Bybit EU spot 0,1% per lato | **0,510x** | −49,3% | −0,226% |
| futures taker 0,05% per lato | 0,685x | — | −0,126% |
| futures maker 0,02% per lato | 0,819x | — | −0,066% |
| buy & hold (stesso campione) | 0,820x | — | — |

Verdetto: **Kronos-small non batte il random walk.** La direzione è testa o croce, le bande sono
troppo strette, e anche a fee zero la strategia perde leggermente. Con le fee spot reali perde
metà del capitale in un anno di trading quotidiano.


## Lettura onesta

- Direzione ≈ testa o croce.
- Bande troppo strette: copertura reale molto sotto la nominale.
- Le fee spot (0,1% per lato) mangiano un trade la cui aspettativa è ~0.

## Da fare

- Review Opus del codice di valutazione (leakage, look-ahead, metriche) prima di chiudere la fase.
- Solo dopo: Base-512 e Small-256, con ok esplicito di Sam.
