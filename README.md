# kronos-lab

Esperimenti onesti di previsione crypto intorno al modello open-source
[Kronos](https://github.com/shiyu-coder/Kronos) (tokenizer + transformer pre-addestrato
sulle candele), senza trading reale: solo dati pubblici, paper trading e misurazione.

**Regole del progetto**

- Nessun ordine reale, nessuna chiave con permessi di trading o prelievo. Solo endpoint
  pubblici di Binance (`/api/v3/klines`).
- Il test set sono gli **ultimi 12 mesi**, mai usati per training o tuning.
- Un forecast fatto a T usa solo candele **chiuse prima** di T.
- Risultati come sono: se Kronos non batte i baseline, si scrive.

## Asset e timeframe

`BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`, `XRPUSDT` — timeframe `1h` e `4h`.

## Setup

```bash
/usr/bin/python3.12 -m venv .venv
.venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.6.0"
.venv/bin/pip install -r requirements.txt
git clone https://github.com/shiyu-coder/Kronos third_party/kronos
```

I pesi (`NeoQuasar/Kronos-small`, `NeoQuasar/Kronos-Tokenizer-base`) vengono scaricati da
Hugging Face al primo uso e restano in `~/.cache/huggingface`.

## Comandi

```bash
# dati: storia completa la prima volta, poi incrementale
nice -n 10 .venv/bin/python scripts/fetch_klines.py
nice -n 10 .venv/bin/python scripts/fetch_klines.py --full

# forecast di prova (30 path, 24 candele) -> out/phase1_forecast.png + .json
nice -n 10 .venv/bin/python scripts/forecast_demo.py --symbol BTCUSDT --tf 1h \
    --samples 30 --horizon 24

# tabella tempo/RAM per 1, 30, 100 campioni
scripts/bench_table.sh
```

## Nota tecnica importante: path veri, non medie

`KronosPredictor.predict` fa la **media** dei campioni prima di restituire il DataFrame.
Con `sample_count > 1` quindi si ottiene una sola serie e i percentili calcolati su quella
serie non sono bande di previsione. Per questo `scripts/kronos_ensemble.py` replica la
funzione di inferenza originale (MIT, ShiYu 2025) senza la media finale: ogni campione
resta un path separato, e le bande 10/25/50/75/90% sono quantili veri tra campioni.

## Struttura

```
data/            Parquet delle candele (fuori da git)
out/             PNG, JSON e cache dei path (fuori da git)
scripts/         fetch, forecast, ensemble, benchmark
third_party/     clone di Kronos (fuori da git, vedi setup)
```

## Licenze

- Kronos: MIT (ShiYu 2025).
- Dati: Binance public API, uso personale di ricerca.
- Nessun asset di terzi committato in questo repo.
