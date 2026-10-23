# Brief per Opus — review leakage del "path judge" (Fase finale Kronos)

Repo `sam-agent-lab/kronos-lab`, branch `feat/path-judge`.
Da leggere: `scripts/path_judge_generate.py`, `scripts/build_path_features.py`,
`scripts/fetch_external.py`, `scripts/path_judge_model.py`, `docs/path-judge-method.md`.

## Cosa fa la pipeline

1. **Generazione** (`path_judge_generate.py`): Kronos-small, contesto 512, **30 path salvati
   tutti** in shard `.npz` float32, `T=1.0`, `top_p=1.0` (nessun troncamento). Solo dati dal
   2025-08-15. Campionamento fisso: 1h alle 00/04/08/12/16/20 UTC, 4h alle 00/12 UTC. Orizzonte
   sempre 24 ore di mercato (1h → 24 candele, 4h → 6). Nessun dato di prezzo successivo
   all'ancora viene usato per generare.
2. **Feature** (`build_path_features.py`): per ogni forecast direzionale di Kronos
   (`prob_up ≥ 0,60` long, `≤ 0,40` short) — target = 1 se il trade nella **direzione di
   Kronos** è profittevole dopo **0,02% per lato** (maker). Feature di contesto: volatilità e
   range realizzati (24/96 candele), volume relativo, distanza da EMA 50/200, RSI(14), ATR(14),
   rendimento 24 candele, funding rate (8h), ora UTC, giorno, asset, timeframe.
   Fonti esterne gratuite, con **ritardo di 2 giorni** (asof): flussi di exchange BTC/ETH
   (Coin Metrics Community), capitalizzazione stablecoin (DefiLlama, variazione 7 giorni),
   rendimenti 1d/5d di Nasdaq-100 e DXY (Yahoo). Ogni fonte è inclusa solo se copre l'intero
   periodo dal 2025-08-15.
3. **Giudice A** (`path_judge_model.py`): LightGBM sulle sole feature di contesto.
4. **Giudice B**: stesse feature di contesto **più** le feature di Kronos e una `prob_up`
   **riponderata sui path**: uno scorer LightGBM assegna a ogni singolo path una probabilità di
   "credibilità" (feature del path: rendimento finale, max drawdown, volatilità, pendenza,
   direzione; più il contesto), e la `prob_up` riponderata è la media dei path pesata per quella
   credibilità. Lo scorer è allenato **dentro ogni fold**, solo sul training di quel fold.
5. **Validazione**: walk-forward in espansione, 5 fold, **purge 3 giorni** (richiesto ≥ 24 h),
   soglia scelta solo in validation, controllo con etichette mescolate, baseline logistica,
   posizioni **non sovrapposte** per serie, IC con **block bootstrap** a blocchi di 7 giorni.
6. **Lockbox**: dal 2026-07-24, sigillato. Lo stadio `lockbox` si rifiuta di partire senza
   `docs/op-review-pathjudge.md`.

## Criteri di successo (fissati prima)

Sul lockbox, Giudice B deve battere Giudice A su **win rate e rendimento dopo fee maker**, con
**almeno 150 trade** non sovrapposti, **IC 95% del win rate sopra il 50%** e **rendimento medio
positivo**. Se B ≈ A, Kronos non aggiunge nulla.

## Domande

1. C'è leakage in una qualsiasi feature? In particolare: `prob_up_reweighted` (lo scorer dei
   path è allenato dentro il fold, ma usa il `prob_up` del forecast stesso), `path_*`,
   `ret_24`, funding (`funding_time <= ancora + durata candela`), e le serie esterne con
   ritardo di 2 giorni (basta? Coin Metrics pubblica con lag variabile).
2. Il purge di 3 giorni è sufficiente, considerando il ritardo di 2 giorni delle serie
   giornaliere e il fatto che l'etichetta dura 24 h?
3. La scelta della soglia sulla validation è pulita? Il grid 0,45-0,75 con "massimo rendimento
   medio e almeno 150 trade" rischia di scegliere un punto fortunato?
4. La riponderazione dei path è impostata in modo sensato (etichetta per path = direzione del
   path uguale a quella realizzata) o introduce un bias di selezione?
5. Il block bootstrap a 7 giorni è adeguato con serie multiple e sovrapposte nel tempo?
6. Verdetto esplicito: **si può eseguire la valutazione sul lockbox?** Se no, cosa correggere.


## Criterio di rendimento (fissato prima del lockbox)

"Return" nei criteri di successo significa **rendimento netto totale dopo fee maker sul periodo
del lockbox**, con capitale diviso in **10 sleeve uguali** (1/10 per asset), nessuna leva e nessun
riuso del capitale mentre una posizione è aperta in quella sleeve. Il rendimento per trade e il
max drawdown si riportano ma **non sono decisivi**. Il Giudice A mantiene la soglia scelta in
validation (0,70): non si cambia per far tornare i conti.

## Tre controlli aggiuntivi richiesti

1. **Path credibility out-of-fold**: verifica che lo scorer che produce `prob_up_reweighted` sia
   allenato **solo** sui path del training di ciascun fold e mai sui path della validation (e
   nemmeno indirettamente, via i pesi o la selezione delle feature).
2. **Sizing/equity**: verifica il calcolo del rendimento totale (`scripts/path_judge_sizing.py`):
   media dei rendimenti delle 10 sleeve, compounding dentro la sleeve, nessun riuso di capitale,
   drawdown calcolato sulla curva di portafoglio e non sulla singola sleeve.
3. **Fill-rate risk**: con fee spot (0,1% per lato) il vantaggio di B sparisce (+0,24% contro
   +1,63% di A). Il verdetto sul lockbox va dato **anche** in quello scenario, dichiarando che il
   risultato con fee maker presuppone di riuscire a eseguire sempre come maker.


## Long/short, taker e confronto con Kronos senza filtro (aggiunte richieste)

Sulla validazione, **il vantaggio è quasi tutto short**: Giudice B short 752 trade, 56,2%,
+19,65% maker; long 142 trade, 52,8%, **−2,71%** (e −4,91% con fee spot). Kronos senza filtro:
short +48,27%, long −15,69%. Il periodo di validazione era ribassista: il verdetto sul lockbox
va dato anche separando i due lati, e va dichiarato che un edge solo-short in un mercato in
discesa non è la stessa cosa di un modello con capacità direzionale.

Con **fee taker 0,05% per lato** (il ripiego realistico quando i limit non si riempiono):
Giudice B +9,85%, Giudice A +3,99%, Kronos senza filtro +13,35%.

**Kronos senza filtro batte B sul rendimento totale con fee maker** (+31,66% contro +16,06%), ma
con drawdown −17,8% contro −9,3% e rovina sulle fee spot (−11,72%). Il punto da verificare è se
il filtro di B valga il costo in rendimento: sul lockbox va riportato anche questo confronto,
non solo A contro B.


## Baseline naive e regola di verdetto (aggiunte finali, prima del lockbox)

Due baseline sullo stesso universo di slot (ogni 4h alle 00 e 12 UTC, orizzonte 24h, 10 sleeve,
una posizione per asset, stesse fee):

| strategia | maker 0,02% | taker 0,05% | spot 0,1% | max DD (maker) |
|---|---|---|---|---|
| Sempre short | **+60,47%** | +30,64% | −7,30% | −26,0% |
| Regola di trend (EMA50 < EMA200 → short) | −12,67% | −28,93% | −49,60% | −28,4% |
| Buy & hold | −61,73% | −68,87% | −77,94% | −68,7% |

**Regola di verdetto, fissata ora:** sul lockbox il Giudice B deve battere **entrambe** queste
baseline (sempre short e regola di trend) sul rendimento totale con fee maker. Se non le batte,
allora Kronos e il giudice **non aggiungono capacità previsionale oltre al trend**, anche se B
dovesse soddisfare i criteri originali (win rate IC sopra 50%, rendimento positivo, ≥150 trade).

Sul lockbox va riportato anche il **buy & hold** del periodo, per sapere se è stato ribassista o
rialzista: senza quel numero non si può dire se un risultato positivo è capacità o solo direzione
del mercato. Le baseline sono in `scripts/path_judge_baselines.py`, con lo stadio lockbox bloccato
dalla stessa guardia.
