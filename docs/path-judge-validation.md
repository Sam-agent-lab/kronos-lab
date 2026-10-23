# Path judge — validazione (solo 4h, 10 asset)

Dati: 6.863 forecast direzionali 4h su 10 asset, 2025-08-15 → 2026-10-21. Lockbox sigillato
dal 2026-07-24 (1.415 righe). Sviluppo: 5.448 righe, di cui 4.525 out-of-fold.
Walk-forward 5 fold, purge 3 giorni, soglia scelta solo in validation, posizioni non
sovrapposte per asset, IC con block bootstrap (blocchi 7 giorni).

| modello | soglia | trade | win rate | IC 95% | net maker/trade | equity maker | max DD | equity spot |
|---|---|---|---|---|---|---|---|---|
| Giudice A (solo contesto) | 0.70 | 226 | 54.0% | 47.7–59.6% | +0.255% | 1.575x | -18.2% | 1.097x |
| Giudice B (contesto+Kronos) | 0.60 | 894 | 55.7% | 51.1–59.8% | +0.178% | 3.304x | -29.4% | 0.790x |
| Kronos senza filtro | 0.00 | 2497 | 51.9% | 49.0–54.8% | +0.101% | 3.616x | -82.0% | 0.066x |
| Controllo etichette mescolate | 0.60 | 523 | 47.4% | 41.8–53.1% | -0.173% | 0.308x | -88.7% | 0.133x |
| Logistica A | 0.70 | 202 | 50.0% | 37.9–62.6% | -0.019% | 0.865x | -41.7% | 0.625x |
| Logistica B | 0.60 | 700 | 50.1% | 44.1–56.1% | -0.008% | 0.651x | -78.1% | 0.212x |

## Validazione con il sizing del lockbox (10 sleeve da 1/10, senza leva)

Capitale diviso in 10 parti uguali (una per asset), una posizione alla volta per sleeve, nessun
riuso del capitale impegnato, nessuna leva. "Rendimento totale" = somma dei rendimenti delle 10
sleeve pesati 1/10: **è questo il numero che decide**. Rendimento per trade e drawdown si
riportano ma non decidono. Le soglie restano quelle scelte in validation: A 0,70, B 0,60.

| modello | fee | trade | win rate | rendimento totale | per trade | max DD | sleeve positive |
|---|---|---|---|---|---|---|---|
| Giudice A (0,70) | maker 0,02% | 226 | 54,0% | **+5,43%** | +0,255% | −3,7% | 6/10 |
| Giudice A (0,70) | taker 0,05% | 226 | 52,2% | +3,99% | +0,195% | −4,1% | 5/10 |
| Giudice A (0,70) | spot 0,1% | 226 | 50,9% | +1,63% | +0,095% | −4,6% | 5/10 |
| Giudice B (0,60) | maker 0,02% | 894 | 55,7% | **+16,06%** | +0,178% | −9,3% | 7/10 |
| Giudice B (0,60) | taker 0,05% | 894 | 54,4% | +9,85% | +0,118% | −10,2% | 5/10 |
| Giudice B (0,60) | spot 0,1% | 894 | 51,8% | **+0,24%** | +0,018% | −11,7% | 4/10 |
| Kronos senza filtro | maker 0,02% | 2.497 | 51,9% | +31,66% | +0,101% | −17,8% | 6/10 |
| Kronos senza filtro | taker 0,05% | 2.497 | 50,7% | +13,35% | +0,041% | −24,5% | 5/10 |
| Kronos senza filtro | spot 0,1% | 2.497 | 48,6% | **−11,72%** | −0,059% | −35,7% | 3/10 |
| Buy & hold (10 sleeve) | maker 0,02% | 10 | 0,0% | **−56,15%** | — | −50,2% | 0/10 |
| Buy & hold (10 sleeve) | spot 0,1% | 10 | 0,0% | −56,31% | — | −50,4% | 0/10 |

Lettura: **A e B hanno guadagnato** (+5,43% e +16,06% con fee maker) in un periodo in cui il
buy & hold long-only ha perso il 56%. Non è "hanno perso meno": è un guadagno, ottenuto in un
mercato in discesa e quasi interamente dal lato short (vedi sotto).

Con il sizing corretto **B batte A sul rendimento totale** (+16,06% contro +5,43%). Il vantaggio
però è appeso alle fee: con taker 0,05% B scende a +9,85%, con spot 0,1% a **+0,24%**, sotto A
(+1,63%). Tutto l'edge di B presuppone di eseguire sempre come maker.

**Kronos senza filtro batte B sul rendimento totale con fee maker** (+31,66% contro +16,06%) ma
ha un drawdown quasi doppio (−17,8% contro −9,3%) e con fee spot affonda a −11,72%. Quindi il
filtro serve a contenere il rischio e i costi, non ad aumentare il rendimento lordo.

## Long contro short

Il vantaggio viene quasi tutto dalle posizioni **short**, in un mercato che scendeva:

| modello | lato | trade | win rate (maker) | rendimento maker | rendimento spot |
|---|---|---|---|---|---|
| Giudice A | long | 51 | 52,9% | +1,71% | +0,89% |
| Giudice A | short | 175 | 54,3% | +3,84% | +0,93% |
| Giudice B | long | 142 | 52,8% | **−2,71%** | **−4,91%** |
| Giudice B | short | 752 | 56,2% | **+19,65%** | +5,72% |
| Kronos senza filtro | long | 587 | 49,4% | **−15,69%** | −23,28% |
| Kronos senza filtro | short | 1.910 | 52,7% | **+48,27%** | +8,89% |

Da segnalare con chiarezza: **il lato long di B perde** (−2,71% maker, −4,91% spot) e il lato
long di Kronos senza filtro perde molto (−15,69%). Il risultato positivo di B è una scommessa
ribassista andata bene in un periodo ribassista: va verificato sul lockbox e va dichiarato che
su un mercato in salita lo stesso modello non ha dimostrato niente.

## Note di lettura

- **B batte A sul win rate** (55,7% contro 54,0%) e sul totale (equity 3,30x contro 1,58x),
  ma **A batte B sul rendimento per trade** (+0,255% contro +0,178%). Il criterio chiedeva
  entrambe le cose: su questo campione B vince una metà e perde l'altra.
- **A ha un IC che include il 50%** (47,7–59,6) con 226 trade; B ha l'IC sopra il 50%
  (51,1–59,8) con 894 trade. Più campione, più fiducia, ma anche più esposizione.
- **Kronos senza filtro** in questo periodo è positivo dopo fee maker (+0,101% per trade) ma con
  drawdown −82% e rovina sulle fee spot (0,066x): inutile in pratica.
- **Il controllo con etichette mescolate è negativo** (−0,173%, win 47,4%): la pipeline non
  produce edge dal nulla, che è il segno che il vantaggio di A e B non è un artefatto.
- **Le logistiche non trovano nulla** (50,0% e 50,1%): il segnale, se esiste, è non lineare e
  debole, e va preso con molta cautela.

## Trade attesi sul lockbox

- Giudice B: 19,8% dei segnali → **~280 trade** attesi su 1.415 righe (sopra il minimo di 150).
- Giudice A: 5,0% dei segnali → **~70 trade** attesi (sotto 150: i suoi numeri di lockbox
  saranno rumorosi e il confronto con B resta sbilanciato sul campione).

## Baseline naive (stesso universo di slot, stesso sizing)

Universo: ogni slot 4h (00 e 12 UTC) dal 2025-08-15 al 2026-07-23, orizzonte 24h, una posizione
alla volta per asset, 10 sleeve da 1/10. Nessun filtro, nessun modello.

| strategia | fee | trade | win rate | rendimento totale | max DD | sleeve positive |
|---|---|---|---|---|---|---|
| **Sempre short** | maker 0,02% | 3.430 | 51,5% | **+60,47%** | −26,0% | 9/10 |
| Sempre short | taker 0,05% | 3.430 | 51,5% | +30,64% | −30,3% | 8/10 |
| Sempre short | spot 0,1% | 3.430 | 51,5% | −7,30% | −36,8% | 4/10 |
| Regola di trend (EMA50 vs EMA200) | maker 0,02% | 3.430 | 49,3% | −12,67% | −28,4% | 4/10 |
| Regola di trend | taker 0,05% | 3.430 | 49,3% | −28,93% | −32,8% | 2/10 |
| Regola di trend | spot 0,1% | 3.430 | 49,3% | −49,60% | −48,5% | 0/10 |
| Buy & hold | maker 0,02% | 3.430 | 46,8% | −61,73% | −68,7% | 0/10 |
| Buy & hold | spot 0,1% | 3.430 | 46,8% | −77,94% | −80,1% | 0/10 |

**Il dato che cambia la lettura:** con fee maker la baseline più stupida — sempre short — rende
**+60,47%**, quasi il doppio di Kronos senza filtro (+31,66%) e quasi quattro volte il Giudice B
(+16,06%). Il periodo era così ribassista che stare sempre short batteva qualsiasi filtro.
La regola di trend, invece, perde (−12,67%): il segnale EMA50/EMA200 non basta.

Conseguenza per il verdetto: sul lockbox B deve battere **anche** queste due baseline, non solo
il Giudice A. Se non lo fa, Kronos e il giudice non aggiungono capacità previsionale oltre al
semplice "essere short in un mercato che scende".
