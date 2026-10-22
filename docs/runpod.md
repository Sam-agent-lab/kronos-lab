# Runpod — setup del 2026-10-22 (modalità "no user in the loop")

Seguito il percorso **No user in the loop** di `https://agents.runpod.io/`: nessun OAuth,
chiave API invece del sign-in, nessuna azione utente richiesta.

## Cosa è stato installato

| componente | esito | dettaglio |
|---|---|---|
| Runpod skills | ✓ | `npx -y skills add runpod/runpod-plugins-official --skill '*' --agent hermes-agent --yes --global` → 7 skill (router `runpod`, lane e journey) |
| Runpod MCP (stdio) | ✓ | server `runpod` in `~/.hermes/config.yaml`, 85 tool, comando `/home/sam/.local/bin/runpod-mcp` |
| Chiave API | ✓ | `RUNPOD_API_KEY` in `.env` (chmod 600, in `.gitignore`), **mai** in `config.yaml`, nei log o nei commit |
| Verifica pod | ✓ | `GET /v1/pods` → HTTP 200, **0 pod** (lista vuota = ok) |

Il wrapper `~/.local/bin/runpod-mcp` fa `set -a; . .env; set +a` e poi `exec npx -y @runpod/mcp-server@latest`:
la chiave resta in un solo file e non entra nella configurazione dell'agente.

## Regole di sicurezza codificate

`scripts/runpod.py` (helper della Fase 3) implementa i vincoli:

- `create` rifiuta di partire se `ore × prezzo/ora` supera il budget residuo passato a mano;
- ogni pod nasce con un **watchdog interno** (`sleep <ore> && runpodctl remove pod $RUNPOD_POD_ID`)
  e il VPS ha un timer di controllo che cancella il pod alla scadenza anche se il watchdog
  non parte;
- `list` stampa solo id, nome e costo/ora; `delete` chiude subito;
- la chiave si legge da `.env`, non viene mai stampata.

## Budget

- Credito caricato: **$30**, nessuna ricarica automatica.
- Tetto rigido Fase 3 + Fase 4: **$30**. Se la stima di un pod si avvicina al residuo, lo script
  si ferma e chiedo prima di procedere.

## Nota sul campo terminateAfter

L'API REST di Runpod non espone un campo `terminateAfter` per i pod: l'auto-terminate è
quindi garantito da due meccanismi indipendenti (watchdog nel pod + timer sul VPS). Se in
futuro l'API lo aggiunge, `scripts/runpod.py` va aggiornato in un punto solo.
