# RUNBOOK — opérer le desk (extract de poche)

> Prérequis : `pip install ccxt pyyaml fastapi uvicorn openai httpx pytest`

## Démarrage standard
```bash
cd /root/aidesk
python3 tools/watchdog.py &            # desk auto-relancé après crash
python3 tools/dashboard.py &           # http://127.0.0.1:8787
```
Variables du watchdog : `AIDESK_ARGS` (ex : `"--tick-seconds 60"`), `AIDESK_MAX_RESTARTS`,
`AIDESK_WATCHDOG_COOLDOWN`. Tests : `python3 -m pytest tests/ -q` (80 tests).
Avec systemd (hôte perso) :
```bash
cp deploy/aidesk*.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now aidesk aidesk-dashboard
journalctl -u aidesk -f
```

## Redémarrage & continuité (testé)
Le desk écrit `state.json` à chaque tick et arrête proprement via `final_report()`.
Au boot il restaure : wallet/vault/frais, positions ouvertes, matrice, agents,
trades clôturés (SQLite = source de vérité). Rien à faire manuellement.

## Supervision manuelle
```bash
touch ctl/PAUSE      # bloque les nouvelles entrées (positions gérées normalement)
touch ctl/SELL_ALL   # liquide tout, le desk continue
touch ctl/KILL       # liquide tout et arrête le desk (watchdog sort proprement)
rm ctl/PAUSE         # reprend
```

## Diagnostics
```bash
python3 tools/stats.py                    # bilan SQLite
python3 tools/llm_test.py                 # santé SKEPTIC + breaker
python3 tools/whale_scan.py --mint <MINT> # whales on-chain
python3 tools/report_week.py -o docs/REPORTS/$(date +%F).md
tail -f events.jsonl                      # journal temps réel
```

## Urgences
1. Suspect une erreur système : `touch ctl/PAUSE` puis lire le dashboard/DB avant tout.
2. Panne réseau : le feed bascule automatiquement en mode OFFLINE (démo) — **les tickets
   restent paper** ; couper plutôt le desk si vous ne voulez pas de données de démo dans la DB.
3. Exposition d'une clé : revoke sur l'exchange/LLM, rotation dans `.env`, restart.
4. Rejouer après tampon : `rm state.json aidesk.db events.jsonl` (remise à zéro DÉFINITIVE).

## Phase 2 (plus tard) — clens d'exchange
Marche à suivre : créer la clé sur l'échange (trade ON / withdrawal OFF / IP whitelist),
l'exposer au desk dans `.env` **en gardant AIDESK_LIVE=OFF** tant que le testnet n'est pas balisé.
Le connecteur live (`live_broker.py`) arrive à la Phase 2, pas avant.
