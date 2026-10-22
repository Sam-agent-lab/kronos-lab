# Fase 3 — accuratezza per sottogruppi (Small-512)

Solo CPU, nessuna GPU. Dati: i 7.296 forecast di `small512` (20 serie, 365 giorni), già sul VPS.
Tabella completa generata da `scripts/subgroup_analysis.py` in
`docs/phase3-subgroups.generated.md`.

Metodo: accuratezza = direzione della mediana al passo finale contro il prezzo realizzato;
intervallo di confidenza di Wilson al 95%; test binomiale a una coda contro il 50%; correzione
**Benjamini-Hochberg** su tutti i gruppi (FDR 5%) perché i gruppi testati sono 22 e con tanti
test qualcuno sembra bravo per caso. Rendimento medio al netto delle fee maker (0,02% per lato),
sulle sole posizioni effettivamente aperte (non sovrapposte).

## L'unico gruppo che resta significativo

**`prob_up < 0,20`** — n = 1.611, posizioni 1.276:

- accuratezza **54,1%** (IC 95% 51,7%–56,5%), p grezzo 0,0005, **p BH 0,011**
- ma il **rendimento medio netto è negativo: −0,068%** per posizione
- dettaglio: segno corretto nel 53,7% delle posizioni, mediana del risultato +0,030%,
  vinci il 51,7% delle volte, ma il **win medio è +1,22% contro un loss medio −1,45%**
  (rapporto 1,19): i pochi errori costano più di quanto rendano le poche vittorie.

Quindi è un vantaggio direzionale **statisticamente reale ma economicamente inutile**: più di
metà delle volte indovina il lato, eppure perde soldi perché le perdite sono più grandi dei
guadagni. È esattamente il caso in cui l'accuratezza non basta: serve il *payoff*.

## Gruppi che sembravano buoni e non lo sono

| gruppo | accuratezza | p grezzo | p BH | perché non vale |
|---|---|---|---|---|
| Asia 00–08 UTC | 52,6% | 0,006 | 0,067 | non passa la correzione per i test multipli |
| ETHUSDT | 52,5% | 0,028 | 0,206 | idem, e rendimento maker negativo (−0,011%) |
| USA 16–24 UTC | 51,7% | 0,047 | 0,260 | idem |

## Gruppi che escludono un vantaggio

- **Regime**: TRENDING 51,1% (n=4.287) e CHOPPY 51,2% (n=3.009), praticamente identici: la
  classificazione in regimi non separa un sottocampione prevedibile.
- **Fasce di `prob_up` alte**: 0,70–0,80 → 47,5% (n=610), >0,80 → 50,7% (n=956). Più il modello
  è sicuro, più sbaglia: la confidenza è mal calibrata, come già mostrava la copertura delle
  bande al 52,2% invece dell'80%.
- **Timeframe**: 1h 50,0%, 4h 51,5%, 5m 51,5%, 15m 51,6% — tutti indistinguibili dal lancio di
  una moneta con questi campioni.

## Conclusione

Nessun sottogruppo con almeno 200 forecast offre un vantaggio direzionale **e** un rendimento
positivo dopo le fee. L'unica deviazione significativa (forte sbilanciamento short) indovina il
lato il 54% delle volte ma ha expectancy negativa. Non c'è un angolo da cui Kronos-small dia
soldi su questo campione.
