# ROADMAP — AIDESK v0.9 → V1.0 (finalisation)

*Émis le 21/10/2026, à l'issue de l'audit du code. Fil conducteur : **le moins de capital
possible tant que la certitude n'est pas établie — la preuve avant la mise.***

---

## 1. État actuel (v0.9 — audité le 21/10/2026)

| Composant | Statut |
|---|---|
| Desk core (14 agents, matrice mutable bornée `_CLAMP`, RISK, AUDIT post-mortem, HEAD, VAULT) | ✅ |
| Données réelles (ccxt, fallback 5 exchanges, paper broker frais 0.1 % + slippage) | ✅ |
| Kill-switchs manuels (`ctl/PAUSE · SELL_ALL · KILL`) | ✅ testés |
| Dashboard web terminal-desk (http://127.0.0.1:8787 — seats, équité MTM, fills, contrôles) | ✅ |
| SKEPTIC LLM gratuit (glm-5.3-flash/z.ai) — objections seulement, jamais d'ordre | ✅ testé (5/5, anti-injection OK, breaker OK) |
| Whales on-chain Solana (mint info, autorités, prix ; top-10 ← clé RPC manquante) | 🟡 fonctionnel partiel |
| Persistance état (wallet/positions/matrice/agents via state.json + SQLite) | ✅ corrigé dans l'audit |

**Constats d'audit traités le jour même** : restauration au redémarrage ; dashboard lié à
`127.0.0.1` (variable `AIDESK_BIND` pour l'ouvrir volontairement) ; roster lu depuis
`desk.yaml` ; guards offline ; snapshot sur KILL ; `.gitignore` (`.env` exclu) ; whale
« inconnu ≠ 0 ». **Limitation documentée** : le RADAR n'enrichit que les 10 movers les plus
vifs du top-40 (les 30 autres paires sont décoratives en v0 → traité en Phase 1.3).

---

## 2. Jalons — v1.0 PAPER stable (fonctionnel, ~2-3 jours)

| # | Livraison | Détail |
|---|---|---|
| 2.1 | **Watchdog** | boucle `systemd` (ou `cron @reboot`) : auto-restart, l'état est restauré (cf. audit) ; le desk survit aux pannes |
| 2.2 | **Tests unitaires** pytest | fills/frais/slippage broker ; caps RISK (max positions, stop journalier, gels) ; `_restore` idempotent ; matrice `_CLAMP` ne sort jamais des bornes |
| 2.3 | **Rapport hebdo auto** | `tools/report_week.py` → markdown : equity, winrate, espérance, n trades, matrice revs, top erreurs (raisons de clôture) |
| 2.4 | **Enrichissement RADAR batch** | OHLCV en 2 appels batch (klines multi-symbôles) pour couvrir le top-40 complet au lieu de 10 |
| 2.5 | Go/No-Go M2 | session paper 72 h sans crash, ni position orpheline, scoreboard cohérent après restart volontaire |

## 3. Phase 1 — Preuve statistique (2-4 semaines, zéro risque)

**Objectif : produire la vérité chiffrée, pas du cash.**

Critères de sortie (tous obligatoires) :
- ≥ **30 trades clôturés** en paper avec données réelles ;
- **espérance nette de frais > 0** sur fenêtre glissante 14 j (sinon : documenter l'absence d'edge et **revenir au tuning**, pas au capital) ;
- **drawdown max < 15 %** du start ;
- < 2 incidents techniques majeurs ;
- SKEPTIC actif sur 100 % des décisions (latence ≤ 20 s couteaux, breaker non déclenché 24 h).

Améliorations optionnelles pendant la collecte :
- **veto SKEPTIC configurable** (`skeptic_veto: true` v1.1) : règle déterministe — verdict ACHAT **et** objection contenant un signal de risque défini → entrée bloquée, journalisée ;
- **journal des features** : persister les features de chaque tick (nouvelle table) → base du backtest Phase 3 ;
- alertes Telegram **lecture seule** (jamais de « signaux » redistribués — c'était le schéma fomo.live).

**Porte Go/No-Go Phase 2** : le dashboard affiche les stats ; décision humaine documentée
(*« on passe réel parce que … / on ne passe pas parce que … »*).

## 4. Phase 2 — Micro-capital réel $10-30 (1-2 semaines après Go)

Prérequis bloquants (aucun contournement) :
- clé API exchange **trade-only, withdrawal OFF**, 2FA, IP whitelist ;
- (a) dry-run testnet de l'ordre complet, (b) live à $10 max au premier passage ;
- réglementaire vérifié côté utilisateur (statut crypto local + KYC de l'échange).

Livraisons techniques :
- `aidesk/market/live_broker.py` — **même interface que PaperBroker** (swap via `live.enabled`) :
  market orders via ccxt, frais réels maker/taker, `amount_to_precision`, `minNotional`,
  qty calculée sur les fills exécutés (partial fills gérés), rejet d'ordre → AUCUN resize ;
- **kill-switch réel** : cancel des ordres ouverts + market close de tout ;
- **réconciliation quotidienne** soldes internes ↔ exchange (script + alerte si delta > 0.5 %) ;
- échéancier strict : $10 → résultats 1 semaine → seulement alors $30.

Paramètres intraitables (constants) :
- sizing max 25 %/position (≈ $7.5), max 3 positions, stop journalier −10 % (−$3),
  drawdown total −15 % → **retour automatique en paper** (mesure de protection, pas de punition).

Attente honnête : la Phase 2 valide (ou invalide) que le système **survit en réel** ; le PnL
se comptera en dizaines de cents — c'est une expérience, pas une source de revenu.

## 5. Phase 3 — Détails de robustesse & extensions (gated, en parallèle)

| Extension | Condition d'activation |
|---|---|
| Feed websocket (ccxt pro `watchTickers`) avec la REST 60 s en secours | Phase 1.4+ seulement si latence bloque des décisions |
| **backtest replay** (`tools/backtest.py`) sur le journal des features | après la Phase 1 (les données existent) — tuning hors-ligne, jamais sur le live |
| Module **memecoin DEX** avec whale.py intégré à RESEARCH (RPC Helius, rugcheck, holders, LP lock, deltas top-10) | **gated par le CEX core** : `dex.enabled` reste false tant que l'edge paper CEX n'est pas prouvé |
| alertes : Telegram bot, retry/auto-restart critiques (watchdog complet) | avec la Phase 2 (l'argent réel exige la rapidité d'alerte) |
| **app mobile** (monitor read-only PWA puis notifications push) | dernier jalon ; **rapport de phase réplica obligatoire avant toute implémentation mobile** (workflow recon → architect → design → build → test) ; package : `com.ghdinteractivestudio.aidesk` |

## 6. V1.0 — Définition de finalisation (checklist de sortie)

- [ ] ≥ 30 trades paper (`PnL net` documenté) **ou** constat d'absence d'edge rédigé et assumé
- [ ] 10+ trades réels $10-30 passés (ou arrêt du programme documenté à un point de garde)
- [ ] tests unitaires verts ; watchdog en place ; dashboard à jour du scope final
- [ ] docs : README (refondu), RUNBOOK (restart/réconciliation/kill/rotation-de-clés), ROADMAP à jour
- [ ] repo GitHub sous org `ghdinteractivestudio` (License, `.env` exclu, secrets hors git)
- [ ] backups horaires auto (aidesk.db, whale.db, state.json) sur emplacement persistant

## 7. Checklist anti-catastrophe (permanente)

1. Clé API **jamais** avec permission withdrawal ; rotation si exposition.
2. Jamais de dépôt custodial chez un tiers « trading desk » type grokaitrade (l'arnaque étudiée).
3. Jamais de décision de risque sur < 30 trades ou sur un winrate court-terme.
4. Ne jamais inventer de promesses de performance (c'est la marque du théâtre que nous combattons).
5. Question à se poser avant chaque jalon : « si le capital était triplé, serais-je aussi
   serein ? » — si NON : renforcer d'abord les garde-fous.

---

*Résumé en une phrase : M2 (stabilité) → Phase 1 (preuve) → Phase 2 (micro-capital avec garde-fous
irréductibles) → Phase 3 (extensions gated) → V1.0 (projet finalisé) — avec à chaque porte un
Go/No-Go explicite, documenté, refusable.*
