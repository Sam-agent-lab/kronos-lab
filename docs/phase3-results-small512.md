# Fase 3 — risultati Small-512

Pod: NVIDIA A40 46 GB, secure cloud, EU-SE-1, **$0,59/h** (la RTX 4090 community US-IL-1 non
aveva istanze libere: sostituzione già approvata da Sam). Costo del run: **$1,78** per 3h00m,
pod distrutto a fine corsa.

Metodo: una previsione al giorno per serie all'ora pseudo-casuale
`H = sha256(seed|symbol|tf|data) % slot_giornalieri`, identica per tutte le varianti. Test set:
ultimi **365 giorni**, mai usati per training né per scegliere soglie. Contesto 512, **30 path**,
`T=1.0` e **`top_p=0.9`** (troncamento del nucleo: i token oltre il 90% di probabilità cumulata
vengono scartati; è il parametro di default dell'inferenza Kronos e non è stato ottimizzato).
4 processi in parallelo sullo stesso pod (`1h`, `4h`, `5m`, `15m`), ognuno con il proprio
`state.json`: nessun file condiviso, zero duplicati.

## Tempi misurati

- **2,0 s** per forecast su GPU (30 path, contesto 512, 24 candele).
- Stesso codice su CPU: 72–79 s con **5** path → la GPU è ~70× più veloce a parità di path.

## Numeri: 8.650 contro 7.300, e i 365 giorni per serie

- **7.300 è il numero giusto**, ed è quello che il piano approvato diceva: 5 asset × 2 timeframe
  (1h, 4h) × 365 = **3.650**, più 5 asset × 2 timeframe (5m, 15m) × 365 = **3.650** → 7.300
  forecast su **20 serie**.
- **8.650 era un errore mio di somma** in un messaggio di stato. Il perimetro non è cambiato.
- **365 giorni per serie**: la prima versione di `plan_days` costruiva la finestra in modo
  inclusivo ai due estremi, quindi alcune serie uscivano con 366 giorni. Corretto
  (`days[-365:]`, finestra canonica identica per ogni serie e ogni variante) e a fine run
  `scripts/prune_window.py` ha tolto il giorno in più dal 5m e dal 15m.
- Restano **4 serie con 364 giorni** (1h BNBUSDT, 1h XRPUSDT, 4h SOLUSDT, 4h XRPUSDT): il
  2026-10-21 la loro ancora cadeva così tardi che le candele di esito non erano ancora chiuse
  nei dati → scarto per progetto, **nessun look-ahead**. Non è un errore e non è un buco nei
  dati (0 buchi superiori a una candela nel periodo).

## Risultati — 7.296 forecast su 20 serie

| timeframe | serie | forecast | direzione a fine orizzonte | copertura banda 80% |
|---|---|---|---|---|
| 1h | 5 | 1.823 | 50,0% | 45,9% |
| 4h | 5 | 1.823 | 51,5% | 55,8% |
| 5m | 5 | 1.825 | 51,5% | 51,0% |
| 15m | 5 | 1.825 | 51,6% | 56,2% |
| **totale** | **20** | **7.296** | **51,2%** | **52,2%** |

- Direzione della mediana: 1 candela **50,5%**, metà orizzonte **49,7%**, fine **51,2%**.
- Calibrazione: dentro la banda 50% **30,5%** (atteso 50%), dentro la 80% **52,2%** (atteso 80%).
  Le bande però non sono strette: la p10–p90 mediana è 1,93% del prezzo contro un range
  realizzato mediano di 1,25%. Sono **larghe e mal centrate**: la mediana sbaglia il centro di
  0,78% in mediana, più del movimento tipico (0,65%). Dettaglio in
  `docs/phase3-band-width.md`.
- MAE della mediana **1,60%** del prezzo; **pinball normalizzato 0,627%** del prezzo (prima era
  in unità di prezzo, non confrontabile fra BTC e XRP).
- Segnali **5.906** su 7.296 (80,9%): long 2.427, short 3.479, flat 1.390.

## Strategia paper (posizioni non sovrapposte per serie)

Regola: long se `prob_up ≥ 0,60`, short se `≤ 0,40`, altrimenti flat; **finché una posizione è
aperta non se ne apre un'altra** nella stessa serie. Posizioni effettivamente aperte: **4.968**;
**1.106** segnali saltati perché la posizione precedente era ancora aperta.

| scenario fee | somma dei ritorni | equity | max drawdown | media per trade | win rate |
|---|---|---|---|---|---|
| nessuna fee (solo modello) | −1,38 | **0,932x** | −13,4% | −0,028% | 50,8% |
| Bybit EU spot 0,1% per lato | −11,31 | **0,566x** | −43,8% | −0,228% | 38,7% |
| futures taker 0,05% per lato | −6,34 | 0,726x | −28,2% | −0,128% | 44,9% |
| futures maker 0,02% per lato | −3,36 | 0,843x | −17,0% | −0,068% | 48,9% |

"Somma dei ritorni" è la somma aritmetica dei rendimenti delle singole posizioni: non è un
rendimento composto e non va letta come percentuale di capitale. L'equity invece è composta
giorno per giorno su un conto unico, con peso uguale fra le serie.

**Buy & hold vero** (per ogni serie: primo prezzo del periodo → ultimo prezzo realizzato, senza
fee e senza segnali): media **−35,8%**, peggiore −45,1%, migliore −23,5%.

## Verdetto

**Kronos-small non ha edge direzionale**: 50,5–51,2% è testa o croce. Le bande sono larghe ma
mal centrate (copertura 52% dove servirebbe 80%), quindi `prob_up` estremi non sono informativi.
Con le fee spot reali la strategia scende a **0,566x** (−43,8% di drawdown); anche a fee zero
resta sotto 1 (**0,932x**). Il vantaggio apparente rispetto al buy & hold (−15,7% vs −35,8% con
fee maker) viene dal fatto che l'anno è stato ribassista e il modello è sbilanciato short
(3.479 short contro 2.427 long), non da capacità previsionale.

## Correzioni applicate dopo la review

1. Posizioni non sovrapposte per serie (prima ogni giorno apriva sopra quella precedente).
2. Buy & hold vero, non somma di ritorni giornalieri.
3. Pinball diviso per il prezzo.
4. "Somma dei ritorni" invece di "ritorno cumulato".
5. Fatti del documento ricontrollati sui file di risultato; nota su `top_p=0.9` e 30 path.

## Da fare

- Studio larghezza bande vs volatilità realizzata: fatto, `docs/phase3-band-width.md`. La banda
  correla con la volatilità realizzata (Spearman 0,753) ma **non più della persistenza**
  (baseline storica 0,750), e a 1h/4h è peggiore.
- Solo dopo, con ok esplicito di Sam: Base-512 e Small-256.
