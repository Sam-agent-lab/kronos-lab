# Fase 7-lite — giudice: risultati dello stadio dev (validation)

CPU only, nessuna GPU. Dataset: **5.906** forecast direzionali di Kronos Small-512
(`prob_up ≥ 0,60` o `≤ 0,40`), 20 serie, tasso base di trade profittevoli dopo fee maker
**49,4%** — cioè Kronos, prese tutte le direzioni, è già sotto il 50%.

Lockbox: ultimi 90 giorni, **1.431** righe, dal 2026-07-24. Sigillato, non toccato in questo
stadio.

## Walk-forward (5 fold in espansione, purge 3 giorni)

| modello | trade | win rate | IC 95% | net maker medio | equity maker | max DD |
|---|---|---|---|---|---|---|
| giudice (soglia 0,66) | 193 | 53,9% | 46,8%–60,8% | +0,031% | 1,001x | −34,3% |
| Kronos senza filtro | 2.231 | 48,1% | 46,0%–50,1% | −0,102% | 0,072x | −93,6% |
| controllo etichette mescolate | 39 | 59,0% | 43,4%–72,9% | +0,102% | 1,035x | −10,3% |
| logistica (baseline) | 35 | 54,3% | 38,2%–69,5% | +0,030% | 0,992x | −24,6% |

## Lettura onesta

- Il giudice **filtra molto**: da 2.231 trade a 193 (−91%). Il risultato migliora in modo netto
  rispetto a Kronos senza filtro (−0,102% → +0,031% per trade), quindi qualcosa impara.
- **Ma non è dimostrato**: l'IC 95% del win rate (46,8%–60,8%) **contiene il 50%**, e il
  controllo con etichette mescolate produce numeri simili (+0,10%, win 59%) con 39 trade.
  Con 193 trade e 5 fold, un risultato del genere è compatibile con il caso.
- La baseline logistica fa quasi lo stesso lavoro del LightGBM: segno che il segnale, se c'è,
  è semplice e debole.
- Con le fee **spot** (0,1% per lato) il giudice va sotto 1 anche in validation (0,735x):
  il filtro non basta a coprire una fee 5× più alta.

## SHAP — cosa guarda il giudice

Le prime feature per importanza media assoluta: `range_96` (0,078), `rsi14` (0,063),
`px_vs_ema50` (0,062), `past_acc_30` (0,062), `weekday` (0,058), `band80_step1` (0,053),
`px_vs_ema200` (0,050), `band50` (0,049).

Cioè: soprattutto **contesto di mercato** (volatilità, RSI, distanza dalle medie) e un po'
di output di Kronos. `prob_up` da solo non compare in cima: il giudice non si sta fidando della
confidenza dichiarata del modello, che infatti è mal calibrata.

## Cosa manca prima del lockbox

- **Review di Opus sul leakage** (brief: `docs/op-review-phase7-brief.md`). Lo stadio lockbox
  dello script si rifiuta di partire senza `docs/op-review-phase7.md`.
- Poi **una sola** valutazione sul lockbox con i criteri fissati prima: IC 95% del win rate
  sopra il 50% e rendimento positivo dopo fee maker, con almeno 150 trade.

## Nota sui dati derivati

- **Funding rate**: copertura 100% del periodo (8h, dal 2025-08-29). Usato come feature.
- **Open interest**: Binance espone solo ~20 giorni di storia pubblica (2026-10-02 → 22), che
  cade **dentro il lockbox**. Includerlo avrebbe significato una feature presente solo in
  valutazione e assente in training: escluso, colonne tenute nel dataset solo per documentare.
