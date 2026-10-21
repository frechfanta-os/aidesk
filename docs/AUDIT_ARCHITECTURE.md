# AUDIT ARCHITECTURE — AIDESK (Phase A, sans modification)

*Base auditée : commit `f0a9e72` (snapshot 7 trades) · date : 2026-10-21 ·
méthode : lecture exhaustive du code + vérifications à l'exécution.*
**Aucun fichier de code n'a été modifié pendant cet audit.**

## 0. Méthodologie et classifications

Chaque conclusion est classée :
- **CONFIRMÉE** — prouvé par lecture du code *et* (quand possible) vérification à l'exécution ;
- **PARTIELLEMENT CONFIRMÉE** — vrai dans un périmètre, lacunes résiduelles identifiées ;
- **NON VÉRIFIÉE** — affirmation à laquelle le code ou l'exécution n'apporte pas de preuve.

Règle respectée : **aucune fonction n'est présumée exister parce qu'elle figure dans le
README** — tout ce qui est déclaré CONFIRMÉ a été lu à sa ligne source, ou exécuté.

## 1. Arborescence réelle et points d'entrée — CONFIRMÉE

```
aidesk/
├── aidesk/                  # package
│   ├── __main__.py          # CLI : --hours, --tick-seconds, --quiet, --offline, --db (aidesk/__main__.py:9-38)
│   ├── runtime.py (448)     # orchestrateur Desk : boucle tick, snapshot, restore, contrôles
│   ├── config.py  (143)     # Settings + Matrix (_CLAMP), chargement desk.yaml
│   ├── store.py   (99)      # SQLite (4 tables) + events.jsonl
│   ├── types.py   (66)      # Features, Signal, Decision, Position, Trade (dataclasses)
│   ├── llm.py     (116)     # SKEPTIC (client OpenAI-compatible unique) + breaker
│   ├── desks/               # radar, research, risk, execution, audit, head, treasury, base
│   └── market/              # feed (ccxt), broker (paper), ledger (cash), whale (Solana RPC)
├── tools/                   # dashboard.py (FastAPI), watchdog.py, stats.py, whale_scan.py,
│                            # llm_test.py, report_week.py, build_site.py
├── tests/                   # 7 fichiers, 26 tests pytest
├── deploy/                  # aidesk.service, aidesk-dashboard.service (systemd)
├── docs/                    # ROADMAP, RUNBOOK, REPORTS/, data/ (site), cet audit
├── desk.yaml                # configuration déclarative
└── README.md, .gitignore
```

- Point d'exécution du desk : `python3 -m aidesk [...]` → `aidesk/__main__.py:main()`.
- Point d'exécution du dashboard : `python3 tools/dashboard.py` → `uvicorn`.
- **2 941 lignes Python** au total (code + tests + outils, hors documentation/site).

## 2. Vérification composant par composant

| # | Revendication (README/desk.yaml/audit) | Évaluation à la source | Classement | Références |
|---|---|---|---|---|
| 1 | RADAR : SCOUT/FEED/SIGNAL en rotation, 3 candidats/scan | rotation `turn % len(agents)`, préfiltres (mom15>0.0008, vol≥1.1×, liq≥60 % du seuil), cooldown 1800 s, top-3 trié | **CONFIRMÉE** | desks/radar.py:9-41 |
| 2 | RADAR ignore les données non fraîches (`fresh`) | le champ `Features.fresh` n'est **jamais** passé à False dans feed.py → filtre inerte | **PARTIELLEMENT CONFIRMÉE** (déclarée ✓ / fonctionnel ✗) | types.py:17, feed.py:103-118, radar.py:24 |
| 3 | RESEARCH : calcul déterministe + thèse structurée | 4 checks + scores clamp01 + agg pondéré (0.35/0.25/0.20/0.20) ; verdict = checks ET agg≥seuil ; thèse générée par `llm.describe()` sans réseau | **CONFIRMÉE** | desks/research.py:19-52, llm.py:41-55 |
| 4 | SKEPTIC : contre-argument LLM, jamais d'action financière | `critique()` retourne une chaîne ; l'objection n'influence jamais verdict/agg ; persistée seulement si verdict | **CONFIRMÉE** (advisory) + lacune C-3 | research.py:40-49 |
| 5 | RISK : veto déterministe | 5 blocages (gel trésorerie, stop journalier, max 3 positions, max 6/h, wallet<$1) ; hystérésis freeze<60 % / unfreeze≥85 % | **CONFIRMÉE** | desks/risk.py:26-67 |
| 6 | EXECUTION : courtier simulé | achat = ask/last ×(1+slippage) + frais 10 bps ; vente symétrique ; PnL = proceeds−usdt | **CONFIRMÉE** | market/broker.py:21-47 |
| 7 | AUDIT : post-mortems + matrice bornée | serrage SL vs perte lente, desserrage après 3 TP consécutifs ; bornes `_CLAMP` testées | **CONFIRMÉE** | desks/audit.py:15-45, config.py:33-51 |
| 8 | HEAD : promotions/licenciements | budget plafonné [1.0, 1.8] au restore ; fire → v2 + reset ; cooldown 6 h ; ≥4 trades crédités requis | **CONFIRMÉE** | desks/head.py:16-37, desks/base.py:34-47, runtime.py:103 |
| 9 | VAULT : registre + gel | sweep 50 % de l'excès > 1.5×start toutes les 24 h ; gel évalué uniquement à l'heure | **CONFIRMÉE** + lacune C-4 | desks/treasury.py:15-26 |
| 10 | LLM intégré, pas de second fournisseur | UN client (`openai.OpenAI` importé localement), key/base/model depuis env ; breaker 3 fail → 600 s ; `max_retries=0` ; streaming ; max_tokens 150 ; temp 0.3 | **CONFIRMÉE** | llm.py:58-116 |
| 11 | État persisté : SQLite + state.json + JSONL | 4 tables (trades/decisions/events/matrix_history) ; snapshot atomique `os.replace` ; restore = SQLite (trades) + state.json (wallet/positions/matrice/agents) | **CONFIRMÉE** | store.py:9-26, runtime.py:63-142, 218-297 |
| 12 | Dashboard : lecture fidèle + contrôles | `/api/state` lit state.json ; `/api/events` formate le JSONL ; `POST /api/ctl` exige l'en-tête anti-CSRF — la page ne l'envoie pas → boutons 403 | **PARTIELLEMENT CONFIRMÉE** (bug P0, §3) | tools/dashboard.py:199-261, l.189 |
| 13 | Tests broker/risk/matrice/research/head/restore/feed | 26 tests verts (exécutés pendant l'audit : `26 passed in 4.75s`) | **CONFIRMÉE** | tests/*.py |
| 14 | Aucun connecteur d'exécution réelle | grep `create_order|fetch_balance|withdraw|sign(|ApiKey` sur aidesk/ + tools/ = **zéro occurrence** | **CONFIRMÉE** | §6 |
| 15 | Secrets hors du dépôt | `.env` exclu (patterns ancrés ; `git check-ignore` ✓) ; aucun `sk-`/token en clair dans le code ; clé absente des parcours de logs lus | **CONFIRMÉE** + pass (test automatique anti-fuite à ajouter) | .gitignore, §6 |
| 16 | Compat ARM64 / Termux / PRoot | environnement actuel **aarch64 + Python 3.14.4** : ccxt 4.5.89, fastapi 0.156.3, pydantic_core 2.50.1, openai 3.35.1, uvicorn 0.54.0 installés et fonctionnels | **CONFIRMÉE sur aarch64 glibc** ; Termux natif (pydantic-core en Rust) **NON VÉRIFIÉ** sur appareil | §6 |

## 3. Trouvailles (anomalies constatées, classées P0→P3)

### P0 — Les boutons du dashboard répondent 403 (anti-CSRF sans miroir UI)
- `api_ctl` exige `x-requested-with == "desk-ui"` (tools/dashboard.py:252).
- L'unique appel JS vers `/api/ctl` ne pose pas cet en-tête (tools/dashboard.py:189).
- **Testé à l'exécution** : POST sans en-tête → `HTTP 403` ; POST avec en-tête → `HTTP 200`
  (action factice `__void_audit_test` sans effet de bord).
- Impact : PAUSE/SELL_ALL/KILL inopérants depuis le web ; les fichiers `ctl/` restent
  fonctionnels (chemin indépendant).
- Correctif proposé (Phase B, 1 ligne) : ajouter `headers:{"X-Requested-With":"desk-ui"}`
  à l'appel fetch.

### P1 — Le filtre anti-péremption est inerté
- `Features.fresh` (types.py:17) n'est jamais repassé à False ; `_basic_features` et
  `_enrich` ne le touchent pas ; le radar filtre `not f.fresh` (radar.py:24) → jamais déclenché.
- Conséquence : des features périmées (si `fetch_tickers` renvoie des tickers anciens)
  ne sont ni marquées ni rejetées. À traiter en Phase C (qualité/provenance).

### P1 — `critique()` (LLM) est appelé pour CHAQUE décision, y compris les refus
- research.py:40 appelle systématiquement le LLM ; l'objection n'est persistée que si
  `verdict` (research.py:49) → coût/latence inutile sur les refus, objection jetée.
- L'appel est synchron dans le tick : en réseau dégradé il peut ralentir le tick
  (breaker 600 s aidant, timeout ~30 s).

### P1 — Le gel trésorerie est évalué uniquement à l'heure
- `check_treasury_freeze()` appelé seulement dans `TreasuryDesk.hour_tick`
  (treasury.py:15-17, runtime.py:382-384) : si net < 60 % du start, jusqu'à 1 h
  d'entrées supplémentaires possibles avant gel. (Le stop journalier, lui, est instantané.)

### P1 — Mélange possible données réelles / démo dans la même base
- Le mode `--offline` (random walk, seed 7) est annoncé (bannière + événement `boot` +
  `feed.offline` dans state.json) mais les trades/decisions écrits dans SQLite/JSONL
  ne portent pas d'étiquette de mode (store.py) → une session offline sur une DB
  existante contamine le corpus de statistiques.

### P2 — Divers
- `PaperBroker.manage()` et `GATE_BY_FEATURES` = code mort (broker.py:13, 49-57).
- `llm.py` : imports `urllib` inutilisés (l.5-6) ; `DEAD_AFTER/COOLDOWN_S/_FAIL` définis
  APRÈS `critique()` (l.114-116) — fonctionne (résolution à l'appel) mais fragile.
- `Store` : pas d'index (trades.ts_close), pas de WAL, pas de migrations
  (CREATE IF NOT EXISTS uniquement, store.py:9-26) ; `events.jsonl` jamais roté.
- desk.yaml : `radar.poll_seconds` et `research.checks` déclarés mais non consommés ;
  `universe.exchanges_fallback` ignoré — la liste est codée en dur (config.py:14). 
- README : « 25 tests » (26 réels) ; liste de dépendances incomplète
  (fastapi/uvicorn/openai/httpx requis pour dashboard + SKEPTIC).
- `unrealized()` décompte les frais de sortie mais pas le slippage de sortie
  (runtime.py:416-423) → MTM légèrement optimiste (~5 bps/position).

## 4. Évaluation Phase D (sécurité & séparation des responsabilités)

| Exigence | Statut | Preuve |
|---|---|---|
| Secrets hors dépôt | **CONFIRMÉE** | `.env` ancré dans .gitignore ; `git check-ignore .env` ✓ ; grep code sans hit |
| Pas de clé/RP dans les logs | **CONFIRMÉE (statique)** / **PARTIELLEMENT (runtime)** | `_load_dotenv` n'imprime rien ; `critique()` avale les exceptions (compteurs `_FAIL` uniquement) ; aucune sortie avec clé repérée dans le parcours lu |
| LLM hors du chemin financier | **CONFIRMÉE** | verdict/agg 100 % déterministes (research.py:36-38) ; sortie LLM = texte seul |
| Sorties LLM validées vs schéma | **NON VÉRIFIÉE** (absent) | texte libre, pas de parser — à construire (Phase B-4) |
| Aucun agent ne mute les règles RISK | **CONFIRMÉE** | risk.py lit `self.s` figé ; seule AUDIT mute la matrice RESEARCH (jamais les caps) |
| Modifications de config versionnées | **PARTIELLEMENT CONFIRMÉE** | seule variable mutée au runtime = matrice, historisée (matrix_history) ; desk.yaml non horodaté au runtime (git suffit) |
| Mode offline explicite | **CONFIRMÉE** | bannière + event `boot` + `feed.offline` dans state.json |
| Étiquette réel/simulé à chaque donnée | **NON VÉRIFIÉE** (absent, voir P1) | — |
| Pas de wallet/connecteur d'exécution | **CONFIRMÉE** | grep exhaustif zéro hit (§6) |

## 5. Jalons — préparation des Phases B–F (sans implémentation à ce stade)

- **B (couches)** : interfaces typées Data Providers (historique/public) ; SKEPTIC
  réfracteur aux entrées invalides (parsing/validation avant tout usage) ; Decision
  Engine séparé (déjà de facto déterministe) ; Dashboard = présentation fidèle
  (state.json déjà canonicalisé ✓).
- **C (couche Solana)** : `whale.py` est déjà un fournisseur remplaçable de facto —
  `rpc()` (env `AIDESK_RPC_URL` + PUBLIC_RPCS, failover 401/403 → endpoint mort,
  429 → backoff, dégradation « PARTIEL »), `features_for_research()` avec sémantique
  `whale_known` (inconnu ≠ 0). À envelopper dans une interface avec provenance
  {source, ts, qualité}. **Aucune hypothèse GMGN** n'est faite (aucun endpoint
  non documenté utilisé). Sources candidates à documenter : RPC publics officiels,
  API Jupiter price (documentée), dumps historiques.
- **D (durcissements)** : étiquette de mode dans trades/decisions (offline bool) ;
  rotation du JSONL ; test de scan de secrets dans CI ; `critique()` en tâche de
  fond ou gated par verdict.
- **E (tests)** : manquants aujourd'hui — timeout LLM + breaker en pytest (actuellement
  testé par l'outil `llm_test --breaker`), anti-CSRF 403/200, idempotence comptable
  (opérations répétées), reproductibilité (replay d'un même dataset), cohérence
  tri-couches (SQLite/state.json/dashboard).
- **F (mesure)** : datasets versionnés, découpe chronologique calibration/validation,
  frais et hypothèses déjà explicites (desk.yaml), comparaison avant/après = git diff +
  rapport apparié (à installer).

## 6. Vérifications exécutées (preuves, pas des promesses)

```
$ python3 -m pytest tests/ -q           → 26 passed in 4.75s
$ grep -rn "create_order|fetch_balance|withdraw|sign(|ApiKey" aidesk/ tools/  → 0 hit
$ git check-ignore .env desk.out ctl/KILL state.json → tous EXCLUS
$ curl -X POST localhost:8787/api/ctl?action=__void_audit_test
         sans en-tête                    → HTTP 403
         avec X-Requested-With: desk-ui  → HTTP 200 {"ok":false,"error":"action inconnue"}
$ curl localhost:8787/api/state         → HTTP 200 (desk vivant : 2 positions à l'instant)
$ uname -m ; python3 --version          → aarch64 ; Python 3.14.4 (stack ARM64 OK)
$ pip list → ccxt 4.5.89 · fastapi 0.156.3 · openai 3.35.1 · httpx 0.28.1 ·
              uvicorn 0.54.0 · pydantic 2.14.1 · PyYAML 6.0.3 · pytest 9.0.2
```

## 7. Conclusion

L'architecture **actuelle est déjà alignée avec la cible Phase B** sur les points de
discipline critiques : LLM purement advisory (jamais dans le chemin financier), RISK
déterministe veto-first, courtier paper sans surface de connection réelle, état persisté
multi-couches avec restauration prouvée en conditions réelles, kill-switchs humains.
Les écarts identifiés restent localisés et bornés : 1 P0 UX (dashboard 403),
3 P1 (fresh inert / critique() sur refus / freeze horaire) et 1 manque transversal pour
la Phase C (provenance + distinction null/inconnu + étiquetage réel vs démo).
La Phase B proposera un plan minimal fichier par fichier — en commençant par le P0
(1 ligne), puis les P1, chaque étape vérifiée par la suite de tests.
