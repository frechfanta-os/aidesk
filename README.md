# AIDESK — Multi-agent trading desk (Phase 0)

Version exécutable du concept vu dans `grokdesk`, mais branchée sur des **données de marché réelles**
( prix publics via ccxt), exécution **paper** au départ, supervision humaine.

## Principes
- Les agents **proposent** (RADAR scan, RESEARCH score + thèse écrite, SKEPTIC contre-argument).
- Un moteur **déterministe** (scoring matrix + RISK) décide et exécute. Le LLM ne place jamais d'ordre.
- AUDIT écrit un post-mortem de chaque trade et serre/desserre la matrice dans des bornes (`_CLAMP`).
- Kill-switch humain : fichiers de contrôle dans `ctl/`.

## Contrôle manuel
```
mkdir -p ctl && touch ctl/PAUSE    # bloque les nouvelles entrées
touch ctl/SELL_ALL                 # ferme toutes les positions, continue à tourner
touch ctl/KILL                     # ferme tout et arrête le desk
```

## Exécution
```
pip install ccxt pyyaml fastapi uvicorn openai httpx pytest
python3 -m aidesk --tick-seconds 60        # run continu, HUD chaque heure
python3 -m aidesk --hours 2 --quiet        # démo bornée, scoreboard final
python3 -m aidesk --offline                # mode secours (random walk) si réseau coupé
```

## Environnement
- `AIDESK_EXCHANGE` (défaut binance ; fallback bybit/okx/kraken/gate automatique)

## LLM / SKEPTIC (optionnel)
Chaque thèse peut recevoir un contre-argument IA d'un modèle OpenAI-compatible.
`aidesk/.env` (local, jamais commité) :
```
AIDESK_LLM_KEY=...
AIDESK_LLM_BASE_URL=https://<provider-openai-compatible>/v1   # le /v1 doit être inclus
AIDESK_LLM_MODEL=glm-5.3-flash      # (actif : z.ai preview)
```
Alternatives gratuites : z.ai (GLM Flash), Groq, OpenRouter (:free), ou **Ollama local**
(`AIDESK_LLM_BASE_URL=http://localhost:11434/v1`, aucun journalisé).
Le LLM ne place jamais d'ordre : il n'écrit que des objections/thèses.
Breaker : 3 échecs consécutifs suspendent l'appel distant 10 min (la clé morte ne bloque pas le desk).

## Whales on-chain (module Solana)
```
python3 tools/whale_scan.py --mint <MINT> --price-symbol BONK/USDT
```
Lecture : supply + autorités mint/freeze directement depuis le compte SPL (RPC léger, gratuit),
```
top-holders (concentration) nécessite un endpoint token : posez une clé RPC gratuite
(Helius/QuickNode/dRPC) dans AIDESK_RPC_URL. Sans clé : verdict « PARTIEL » honnête.
```
Historique : `whale.db` (delta top10 entre scans → détection de movements de whales).
Features `features_for_research()` prêtes pour la future integration RESEARCH du module DEX.

## Supervision & tests (M2)
- **Watchdog** : `python3 tools/watchdog.py &` (auto-relance après crash ; `AIDESK_ARGS`,
  `AIDESK_MAX_RESTARTS`) — unités systemd prêtes dans `deploy/`.
- **Rapport hebdo** : `python3 tools/report_week.py -o docs/REPORTS/<date>.md`.
- **Cohérence** : `python3 tools/verify_desk.py` — réconciliation SQLite ↔ state.json ↔
  events.jsonl (code 0 OK / 1 avertissements / 2 fatal).
- **Dataset versionné** : `python3 tools/export_dataset.py` — corpus CSV + manifeste
  SHA-256 dans `docs/data/exp/` (étiqueté : données expérimentales, aucune garantie).
- **Tests** : `python3 -m pytest tests/ -q` (80 tests : broker, risk, matrice, research, head,
  restore, feed, dashboard, fraîcheur, skeptic, trésorerie, sessions, nettoyage).
- **Runbook opérations** : `docs/RUNBOOK.md`.

## Site de suivi (GitHub Pages)

Vue spectacle publique : **https://frechfanta-os.github.io/aidesk/**

- **SNAPSHOT** : données du desk au moment du dernier push (par défaut).
- **SPECTATEUR LIVE** : bouton `CONNECT` avec l'URL du desk (ex. `http://127.0.0.1:8787`
  via tunnel SSH `ssh -L 8787:localhost:8787 <host>`) — rafraîchit toutes les 15 s.
- Suivre le développement : onglet [commits](https://github.com/frechfanta-os/aidesk/commits/main).

Mise à jour du snapshot : `python3 tools/build_site.py && git add docs/data && git commit -m "snapshot" && git push`.

## Audit & roadmap
Audit du 21/10/2026 : 3 criticités corrigées (persistance du portefeuille/positions/matrice
au redémarrage via `state.json`+SQLite, dashboard lié à `127.0.0.1` par défaut (`AIDESK_BIND`
pour l'exposer), roster d'agents lu depuis `desk.yaml`). Limitation connue : le RADAR n'enrichit
que les 10 movers les plus vifs du top-40 (les autres paires sont décoratives en v0).
Feuille de route complète vers la finalisation : **docs/ROADMAP.md**.

## Roadmap
- [x] Phase 0 : squelette desks + données réelles + paper broker + audit + kill-switch
- [ ] Phase 1 : collecte de statistiques paper sur 2–4 semaines (rapport hebdo, courbes)
- [ ] Phase 2 : micro-capital réel ($10–30) — exiges : clés API trade-only sans withdrawal, cut dur −15 %
- [ ] Phase 3 : scaling graduel si PME paper > 0 après frais ; module DEX memecoin plafonné (désactivé ci-dessous)

## Sécurité
Le module memecoin DEX (`desk.yaml: dex.enabled`) est **false** en v0 : aucun flux vers pump.fun/DEX
tant que le core CEX n'a pas démontré un edge net de frais en paper.
