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

**Tabella tempo/RAM** (BTCUSDT 1h, 24 candele, CPU, un processo per misura)

| campioni | inferenza | s/campione | picco RAM |
|---|---|---|---|
| 1 | 11,4 s | 11,4 | 524 MB |
| 30 | 359 s | 12,0 | 2.026 MB |
| 100 | 1.767 s (29 min) | 17,7 | 4.080 MB |

**Costo:** €0 (solo API pubbliche e calcolo locale).

**Conseguenza per la Fase 3:** 30 path × 24 passi costano ~6–10 minuti di CPU. Un walk-forward
su 12 mesi per 5 asset × 2 timeframe, con 1 path + 30 campioni, non sta nei tempi: servirà un
piano di campionamento esplicito (es. un forecast ogni N giorni, orizzonte breve) e va
concordato prima di partire.

## 2026-10-22 — Revisione Opus e varianti di velocità (chieste da Sam prima della Fase 2)

**Opus (1 call, medium)** — `docs/op-review-verdict.md`
- Difetto confermato: `auto_regressive_inference` fa `z.reshape(-1, sample_count, …)` e poi
  `preds = np.mean(preds, axis=1)`; `predict` riceve un solo path. La de-normalizzazione è
  lineare, quindi la media cancella la dispersione, non la sposta.
- Replica fedele riga per riga; differenze trovate: mancava `.to(device)`, controllo NaN
  assente, caso limite volume/amount, e `_stamps` non verificata (la più insidiosa).
  Rischio dichiarato: medio, con richiesta di test di equivalenza.
- Corretto tutto + `scripts/parity_test.py`: timestamp identici, media dei path = `predict`
  con errore relativo massimo **9,56e-08**.

**Varianti di velocità** (10 path, 24 candele, stesso seed, senza nice) — `docs/phase1-speed.md`
- `threads=6`: **−23,8%** tempo, numeri identici → adottato come default.
- `ctx256`: **−67%** ma forecast diverso (−2,6% mediana, bande più strette).
- `int8`: **−57,5%** ma bande ~4× più strette → non calibrate, scartato.

**Decisioni per la Fase 3 (da Sam)**
- Tre varianti: Small ctx512, Base ctx512, Small ctx256.
- Ora del forecast giornaliero **casuale ma con seed fisso**, la stessa per tutti i modelli,
  così non si valuta sempre la stessa fascia oraria.
- Preventivo GPU approvato in linea di principio; **chiedere conferma prima di creare il pod**.

## 2026-10-22 — Fase 2: servizio, scheduler, DB, digest

- `service/core.py`: forecast con 20 path di default, bande 10/25/50/75/90, `prob_up`,
  regime (`TRENDING_UP`/`TRENDING_DOWN` se ≥70% dei path dallo stesso lato, soglia
  configurabile; altrimenti `CHOPPY`), `torch.set_num_threads(6)`.
- `service/app.py`: FastAPI su **127.0.0.1:8770** — `/health`, `/latest`, `/forecast`
  (serve la cache; `refresh=1` ricalcola). Mai esposto in rete.
- `service/runner.py`: precalcolo alla chiusura della candela; salta se la candela è già
  in cache. Un giro completo delle 10 serie: **~44 min** su CPU (1h ≈ 410–440 s per serie,
  4h ≈ 103–113 s con orizzonte 6).
- `service/store.py`: SQLite `var/forecasts.sqlite`, una riga per forecast, con payload
  completo; UNIQUE su (symbol, tf, model, context, last_candle) contro i duplicati.
- `service/digest.py` + cron Hermes 08:00 (`no_agent`): una riga per asset con regime,
  `prob_up`, mediana, larghezza banda.
- systemd utente: `kronos-svc.service` (uvicorn, Restart=always), `kronos-runner.timer`
  ogni 10 min con `MemoryMax=6G` e `TimeoutStartSec=3600`.
- **Fuso**: tutto in UTC (log con suffisso `Z`, `generated_at` con `+00:00`, digest dichiara
  UTC). Il bug dei minuti negativi nel heartbeat veniva dal parsing di
  `ActiveEnterTimestamp` (ora locale) come UTC; ora si usa il timestamp monotono.

Risultati del primo giro (20 path, 10 serie): 10 righe in DB, tutte le serie in cache.
Segnali più forti: BTC 1h `TRENDING_UP` prob_up 0.85 (+1.63%), SOL 4h `TRENDING_DOWN`
prob_up 0.30 (−1.59%), XRP 1h `TRENDING_UP` prob_up 0.70 (+1.77%, banda 9.88%).

## 2026-10-22 — Aggiornamenti Fase 3 chiesti da Sam

- **Pod separati**: uno per variante, ordine `small512` → (risultati + ok di Sam) → `base512`,
  `small256`. Mai due pod insieme, auto-terminate 3 h ciascuno.
- **Ripresa**: ogni forecast appeso subito a `results/<variant>/<tf>_<symbol>.jsonl`, `state.json`
  per serie, e il VPS tira i risultati dal pod ogni 10 minuti con rsync (nessuna chiave del VPS
  sul pod). Pod morto = si riparte dal punto di stop.
- **Fee**: scenario principale 0,1% per lato (Bybit EU **spot**), alternativo futures
  0,02% maker / 0,05% taker. Soglie long ≥0,6 / short ≤0,4 fissate prima.
- **Short-term**: 5m e 15m come esperimento separato, **solo** `small512`, stessa ora casuale
  giornaliera (seed fisso), orizzonte 12 candele, 30 path.
- Preventivo aggiornato: `small512` 1,5–3 h, `base512` 2–3 h, `small256` ~1 h → **€2–5**,
  entro il tetto €30 con la Fase 4.

## 2026-10-22 — Setup Runpod (modalità no user in the loop)

- Skill Runpod installate per `hermes-agent` (router + lane + journey, 7 skill) con
  `npx -y skills add runpod/runpod-plugins-official --skill '*' --agent hermes-agent --yes --global`.
- MCP `runpod` registrato in stdio (85 tool) con wrapper `~/.local/bin/runpod-mcp` che legge
  `RUNPOD_API_KEY` da `.env`: la chiave non sta in `config.yaml`.
- Chiave in `.env` chmod 600, `.env` in `.gitignore`; mai stampata.
- Verifica: `GET /v1/pods` → HTTP 200, **0 pod attivi**.
- Credito: $30 senza ricarica automatica; tetto rigido $30 per Fase 3 + Fase 4.
- `scripts/runpod.py`: create con controllo budget, list, delete; `docs/runpod.md` spiega i due
  meccanismi di auto-terminate (watchdog nel pod + timer sul VPS) perché l'API REST non ha
  `terminateAfter`.

## 2026-10-22 — Fase 3, run Small-512 completato

- Pod: A40 46 GB secure EU-SE-1 ($0,59/h), 4 processi in parallelo (1h, 4h, 5m, 15m) come
  autorizzato da Sam. GPU al 100%, VRAM 4,9/46 GB, nessun OOM, nessun duplicato.
- 7.296 forecast su 20 serie, ~2,0 s per forecast con 30 path (CPU: 72–79 s con 5 path).
- **Costo reale: $1,78** (3h00m di pod, saldo 30,00 → 28,22). Pod distrutto, lista vuota.
- Risultati: direzione 50,5% / 49,7% / 51,2%; copertura banda 80% 52,2%; equity spot 0,510x
  (max DD −49,3%), maker 0,819x, buy & hold 0,820x, senza fee 0,922x. **Non batte il random walk.**
- 4 serie con 364 giorni invece di 365 (1h BNB, 1h XRP, 4h SOL, 4h XRP): l'ancora del 2026-10-21
  cadeva così tardi che le 24/6 candele di esito non erano ancora chiuse → scarto per progetto
  (nessun look-ahead), non un errore e non un buco nei dati. Nessun ricalcolo necessario.
- `plan_days` corretto su finestra canonica di 365 giorni; `prune_window.py` ha tolto il giorno
  in più a 5m/15m (366 → 365).

## 2026-10-22 — Correzioni post-review su Fase 3 (PR #4)

- `backtest.py`: posizioni non sovrapposte per serie (4.968 posizioni, 1.106 segnali saltati),
  buy & hold vero (prima prezzo → ultimo esito: media −35,8%), pinball normalizzato sul prezzo
  (0,627%), etichetta "somma dei ritorni".
- Numeri corretti: equity spot **0,566x** (max DD −43,8%), taker 0,726x, maker 0,843x,
  nessuna fee 0,932x. Direzione 50,5/49,7/51,2%, copertura 80% al 52,2%.
- Documento `docs/phase3-results-small512.md` riscritto: fatti verificati sui file di risultato,
  nota su `top_p=0.9` e 30 path, spiegazione delle 4 serie con 364 giorni.

## 2026-10-22 — Studio larghezza bande vs volatilità realizzata (solo CPU)

- `scripts/band_width_study.py`: per ogni forecast confronta banda p10–p90 prevista, range
  realizzato e range delle N candele precedenti (baseline di persistenza).
- In pool: Spearman 0,753 (banda) contro 0,750 (baseline), Pearson 0,556 contro 0,607. A 1h e 4h
  Kronos è peggiore della baseline (0,288 vs 0,389 e 0,311 vs 0,330); a 5m/15m equivalenti.
- Banda mediana 1,93% del prezzo contro range realizzato 1,25% e movimento tipico 0,65%: larga,
  ma copre solo il 52,2% degli esiti invece dell'80%. Errore mediano del centro 0,78%: il
  problema è il centro, non la larghezza.
- Nessuna GPU usata (Vietato dalla richiesta: solo VPS).
