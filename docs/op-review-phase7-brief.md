# Brief per Opus — review leakage Fase 7-lite (giudice)

Repo: `sam-agent-lab/kronos-lab`, branch `feat/phase7-judge`.
File da leggere: `scripts/build_judge_dataset.py`, `scripts/judge_model.py`,
`scripts/fetch_derivatives.py`, `docs/phase7-lite-dev.md`.

## Cosa fa la pipeline

1. `build_judge_dataset.py` costruisce una riga per ogni forecast **direzionale** di Kronos
   (`prob_up ≥ 0,60` long, `≤ 0,40` short) sul run Small-512. Target = 1 se il trade nella
   direzione di Kronos è profittevole **dopo 0,02% per lato** (maker), altrimenti 0.
   Feature: output di Kronos (prob_up, ritorno mediano, larghezze bande, accordo dei path,
   skew, regime), accuratezza passata di Kronos sulla serie (solo esiti già realizzati),
   volatilità/range realizzati, volume relativo, trend vs EMA 50/200, RSI(14), ATR(14),
   ora UTC, giorno della settimana, asset, timeframe, funding rate (8h) e open interest.
   Ogni feature usa solo candele con `open_time + durata <= ancora` (la candela dell'ancora è
   chiusa) e funding con timestamp `<= chiusura dell'ancora`.
   **Open interest escluso dalle feature**: Binance conserva ~20 giorni di storia pubblica,
   quindi la feature esisterebbe solo nel lockbox.
2. `judge_model.py --stage dev`: walk-forward a 5 fold in espansione sul periodo pre-lockbox,
   con **purge di 3 giorni** fra training e validation (l'etichetta dura fino a 24h; il purge
   copre anche la finestra di 30 forecast dell'accuratezza rolling). LightGBM piccolo
   (`num_leaves=7`, `max_depth=3`, `min_child_samples=80`, `reg_lambda=5`, `learning_rate=0,03`),
   baseline logistica con standardizzazione e `class_weight="balanced"`, **controllo con
   etichette mescolate** nella stessa procedura.
   La soglia di ingresso è scelta **solo sulla validation** (massimo ritorno netto con almeno
   150 trade) fra 0,45 e 0,75.
3. `judge_model.py --stage lockbox`: si rifiuta di partire senza `docs/op-review-phase7.md`.
   Allena su tutto il pre-lockbox, applica la soglia già scelta, valuta **una volta** sugli
   ultimi 3 mesi (1.431 righe, dal 2026-07-24).

## Criteri di successo, fissati prima

IC 95% del win rate sopra il 50% **e** rendimento medio positivo dopo fee maker sul lockbox,
con almeno 150 trade. Altrimenti: fallito.

## Domande per Opus

1. C'è leakage o look-ahead in una qualsiasi feature? In particolare: `past_acc_30`,
   `agreement`, `band80_step1`, `mean_vs_median`, funding (`funding_time <= close_at`).
2. Il purge di 3 giorni è sufficiente con orizzonti fino a 24h e con il lockbox di 90 giorni?
3. La scelta della soglia sulla validation è fatta in modo pulito o il grid search introduce
   overfitting che poi si scarica sul lockbox?
4. Il controllo con etichette mescolate è impostato correttamente? Nel dev dà 39 trade,
   win 59% e net +0,10%: è normale con così pochi trade o indica un problema di procedura?
5. La definizione del target (fee maker su entrambi i lati, nessuno slippage) e il confronto
   con "Kronos senza filtro" e buy & hold sono corretti?
6. Verdetto esplicito: **si può eseguire la valutazione sul lockbox?** Se no, cosa va
   corretto prima.
