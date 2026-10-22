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
