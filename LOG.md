# LOG

Decisioni, risultati e costi, in ordine di data. Solo cose vere e misurate.

## 2026-10-22 — Fase 1: setup e smoke test

**Fatto**
- Repo `sam-agent-lab/kronos-lab` (pubblico), branch `feat/phase1-setup`.
- venv Python 3.12 con PyTorch 2.6.0 **CPU** (`+cpu`), versioni pinnate in `requirements.txt`.
- Clone `shiyu-coder/Kronos` in `third_party/` (MIT), pesi `NeoQuasar/Kronos-small` +
  `NeoQuasar/Kronos-Tokenizer-base` da Hugging Face (~111 MB in cache).
- Download completo Binance klines: **10 file** (5 asset × 2 timeframe), **459.532 candele**
  dal 2017-08-17 al 2026-10-22. Script `scripts/fetch_klines.py`, incrementale.
- Forecast di prova: BTCUSDT 1h, ultime 512 candele chiuse → 24 candele, 30 path.

**Bug trovato e corretto (importante per tutte le fasi dopo)**
`KronosPredictor.predict` fa `np.mean` sui campioni *dentro* la funzione di inferenza:
con `sample_count>1` restituisce una sola serie (la media). I percentili calcolati su quella
serie non sono bande di previsione. `scripts/kronos_ensemble.py` replica l'inferenza
originale senza la media: ogni campione resta un path, le bande sono quantili veri.

**Risultato del forecast (BTCUSDT 1h, 30 path, orizzonte 24)**
- ultimo close: 81.750,01
- mediana a 24 candele: 82.959,30 (+1,48%)
- `prob_up`: 0,933
- larghezza banda a fine orizzonte: 10–90% = 2,90%, 25–75% = 1,30%
- tempo inferenza: 343–582 s su CPU (varia con il carico del VPS), caricamento modello ~7–14 s

**Costo:** €0 (solo API pubbliche e calcolo locale).

**Conseguenza per la Fase 3:** 30 path × 24 passi costano ~6–10 minuti di CPU. Un walk-forward
su 12 mesi per 5 asset × 2 timeframe, con 1 path + 30 campioni, non sta nei tempi: servirà un
piano di campionamento esplicito (es. un forecast ogni N giorni, orizzonte breve) e va
concordato prima di partire.
