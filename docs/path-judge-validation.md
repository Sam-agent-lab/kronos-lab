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
