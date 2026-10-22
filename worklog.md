# worklog — Phase B (corrections contrôlées)

*Suivi de la Phase B après audit `67fbf75`. Chaque entrée : date, changements réels,
commandes exécutées, résultats de tests, limites restantes.*

---

## B1 — Dashboard anti-CSRF (en-tête manquant dans l'UI) — **2026-10-21** ✅

**Problème reproduit avant correction** (obligation : ne pas croire l'audit sur parole)
```
$ curl -X POST localhost:8787/api/ctl?action=__probe        # sans en-tête
{"detail":"contrôle réservé à l'UI du desk"} HTTP 403
$ curl -X POST -H "X-Requested-With: desk-ui" ...?action=__probe
{"ok":false,"error":"action inconnue"} HTTP 200
$ grep -n 'api/ctl' tools/dashboard.py                      # l.189 : fetch sans en-tête
```
Reproductions à l'exécution sur le dashboard **réel en cours**, avec une action
de contrôle inconnue (aucune commande PAUSE/SELL_ALL/KILL déclenchée contre le desk).

**Changement effectué (1 ligne)**
- `tools/dashboard.py:189` : le fetch des boutons de la page pose désormais
  `headers:{"X-Requested-With":"desk-ui"}`. La vérification serveur (l.252) et la
  sémantique des commandes (`ctls` fichiers `PAUSE/SELL_ALL/KILL`) sont inchangées.

**Tests ajoutés** — `tests/test_dashboard.py` (11 tests, TestClient isolé,
`ROOT` monkeypatché vers `tmp_path` : zéro écriture dans `ctl/` réel) :
rouge avant correctif → `1 failed, 10 passed` (le test page, comme prévu) ;
vert après → `11 passed`. Suite complète : **37 passed in 10.14s** (26 précédents + 11).
Couverture : 403 sans en-tête pour tout action · action inconnue sans effet ·
toggle PAUSE (créer/supprimer) · PAUSE/SELL_ALL/KILL touchent leurs fichiers isolés ·
la page pose l'en-tête · GET state/events sur fichiers isolés · préflight CORS
POST refusé / GET autorisé.

**Vérifications diff** : `git diff --check` OK · diff = 1 ligne · scan secrets
sur le diff : aucun hit (contenu de `.env` jamais affiché) · aucun fichier de
config (`desk.yaml`), de base (`aidesk.db`), d'état ou journal modifié.

**Limites restantes** : le dashboard en cours d'exécution sert l'ancien HTML tant
qu'il n'est pas relancé — relance seule du processus dashboard prévue juste après
le commit (RUNBOOK : kill par PID précis, desk/watchdog intacts), puis vérification
de la page servie.

---

## B2 — Fraîcheur et qualité des Features — **2026-10-21** ✅

**Cartographie vérifiée** (grep + lecture) : création = `feed._basic_features` (live),
`feed._offline_snapshot` (démo), reconstructions restorées `runtime` l.78/l.125
(positionnelles, 9 args → compatibilité additive garantie) ; transformation =
`_enrich` en place ; consommation = `radar.scan` (gate d'entrée),
`runtime._manage/_lookup/_snapshot` (prix, indépendant de la fraîcheur).

**Taxonomie implémentée** (`types.py`) : `Features.ts` (epoch d'observation)
+ `age(now)` → None si inconnu (ts≤0), + `usable(now, max_age)` = fresh ET âge connu
ET âge ≤ seuil. Distingué : fraîche / périmée (calculable mais ancienne, ex. epoch
1970) / absente (aucun objet / jamais des zéros) / invalide (ts négatif) /
fraîcheur inconnue (ts=0 — cas des restaurations historiques).

**Seuil introduit et justifié** : aucun seuil n'existait → `feed.freshness_s: 300`
(desk.yaml + `Settings.freshness_s`, défaut 300 si yaml absent). Justification :
5× l'intervalle nominal de refresh (60 s), enrich top-40 ≈ 16 s inclus, tolérance
de throttle. La gestion des positions (sorties TP/SL/TIMEOUT) reste prix-basée et
n'est PAS retirée par la fraîcheur. `state.json` expose désormais `feed.ts/age_s`.

**Policy restore** : les features reconstruites d'un state.json sans ts (ts=0)
marquent fraîcheur inconnue → jamais utilisées pour des entrées ; mises à jour au
premier refresh réel ; les sorties et le MTM restent fonctionnels.

**Tests ajoutés** — `tests/test_freshness.py`, 13 tests (red→vert ; 1 échec
diagnostiqué honnêtement : `ts=1.0` est PÉRIMÉ, pas inconnu — assertion corrigée,
pas affaiblie). Suite complète : **50 passed in 7.44s** (37 précédents + 13).
Smoke de wiring temporaire : Desk chargé avec `freshness_s` propagé (radar.fresh_s
= 300), 8/8 features offline datables, DB/jsonl dans /tmp (jetés ensuite — aucune
écriture dans les données réelles).

**Diff** : 41 insertions / 5 suppressions sur 6 fichiers (types, config, feed,
radar, runtime, desk.yaml feed uniquement) · scan secrets clean · aucune donnée
trackée modifiée · `git diff --check` OK.

**Incident noté et annulé** : un edit accidentel sur la condition offline de
`feed.refresh` a été détecté typings après coup et **révert** (vérifié `git diff`
nul sur feed.py avant l'ajout réel du ts).

**Limites restantes** : le desk en cours (PID 22191) ne voit pas encore la gate —
redémarrage supervisé par watchdog+restore juste après le commit (procédure
RUNBOOK, integrity de la batterie 3 positions ouverte réelle vérifiée avant/après).

---

## B3 — Politique d'appel SKEPTIC (LLM consultatif borné) — **2026-10-21** ✅

**Flux reconstitué** : SIGNS radar → `research.decide()` calcule checks/scores/agg/
verdict **déterministes d'abord** ; `llm.critique()` était ensuite appelé
SYSTÉMATIQUEMENT (y compris sur refus — objection calculée puis jetée :
`objection=obj if verdict else None`). Fenêtre utile identifiée : uniquement quand
verdict=True (candidat accepté, avant le desk d'exécution) — le refus déterministe
rend l'analyse inutile ; données invalides → ce candidat n'atteint jamais RESEARCH
(gate radar fraîcheur B2), veto RISK → appelé après la décision (hors chemin LLM).

**Reproduction en rouge** (5 failed / 3 passed) : appel sur refus compté (1 au
lieu de 0) · exception critique détruit la décision (TimeoutError remonte) ·
objection de 465+ chars stockée telle quelle · RuntimeError stocké COMME
texte d'objection · + 1 bug de MON test corrigé (exception-instance passée comme
fonction patchée — erreur de test, pas du code desk).

**Correctif** (`aidesk/desks/research.py`, +25/−6) :
1. `critique()` appelé UNIQUEMENT si verdict=True ;
2. try/except autour de l'appel : toute panne LLM (timeout/HTTP/breaker/bug)
   → `obj=None`, la décision déterministe est conservée (jamais perdue) ;
3. `_sanitize_objection()` : sortie LLM = texte non fiable — non-str → None,
   whitespace collapsé, borné à 160 chars, vide → None ;
4. le LLM ne touche toujours rien : verdict/agg inchangés, zéro accès au ledger
   (test dédié `test_ledger_intact_apres_tous_les_senarios`).
Config inchangée : Z.ai `glm-5.3-flash`, breaker 3 échecs → 600 s conservé(s)
(aucun fournisseur/endpoint/clé ajouté).

**Comportement de repli documenté** : SKEPTIC indisponible/trop lent/mal formé
→ objection None, décision identique à sans-LLM ; breaker ouvert → `critique()`
rend None avant tout import client (test prouve zéro instanciation via garde).

**Tests ajoutés** — `tests/test_skeptic_policy.py`, 8 tests. Suite complète :
**58 passed in 19.81s**. Diff : recherche.py seul (+8 tests fichier) · scan
secrets clean · aucune donnée/config touchée · `git diff --check` OK.

**Limites restantes** : la politique est au niveau décision (monde synchrone) ;
un appel LLM peut toujours ralentir le tick jusqu'au timeout read ~20 s — un
passage en tâche de fond est reporté (amélioration, pas requis : breaker présent).

---

## B4 — Gel de trésorerie évalué à chaque tick — **2026-10-21** ✅

**Constat reproduit par lecture** : `check_treasury_freeze()` (risk.py:53-58) n'était
appelé QUE dans `TreasuryDesk.hour_tick()` → un net tombant sous 60 % du start
entre deux heures laissait jusqu'à 1 h d'entrées possibles.

**Correctif** (`aidesk/runtime.py`, +2) : `self.risk.check_treasury_freeze()` dans
`tick()` juste avant le bloc radar/entrées. **Aucun seuil ou politique modifié**
(hystérésis 60 %/85 %, gel journalier, sizing, semua caps inchangés) ; `hour_tick`
conservé (appel idempotent). La fonction est stateless/re-dérivée du ledger →
redémarrage sûr sans étiquette persistée.

**Tests ajoutés** — `tests/test_treasury_freeze.py`, 7 tests : gel activé entre
deux heures + veto « gel trésorerie » via `allow()` · bande intermédiaire reste
gelée (hystérésis) · dégel exactement à 85 % · wiring : aucune entrée paper alors
que verdict=True (achats capturés = 0) · reprise dès net ≥ 85 % au tick suivant ·
re-dérivation au boot (nouveau Desk gélifié au 1er tick sans état persisté) ·
positions ouvertes toujours gérées pendant le gel (sorties non bloquées).
Horloge non modifiée : `now` paramétré, chdir(tmp_path) pour l'isolation.

Suite complète : **65 passed in 15.89s**. Diff : runtime.py +2 lignes + nouveaux
tests · `git diff --check` OK · scan secrets vide · données/config intacts.
Redémarrage supervisé du desk après commit (watchdog PID précis, restore
vérifié avant de conclure).

---

## B5 — Provenance de session (live/offline), migration additive — **2026-10-21** ✅

**Constat reproduit** : le schéma trades ne portait aucun mode ; une session
`--offline` (ou une bascule offline après 2 échecs réseau) écrivait ses trades
de démo SANS marque → contamination silencieuse du corpus de performance.

**Migration additive, transactionnelle, sans réécriture** (`aidesk/store.py`) :
`ALTER TABLE trades ADD COLUMN mode TEXT DEFAULT 'unknown'` appliquée à l'ouverture
(Store.__init__, au boot du desk) — les lignes historiques préservées à l'identique,
lues 'unknown'. **Stratégie documentée** : sauvegarde `cp aidesk.db <bak>` avant le
1er boot BB5 en production (effectuée, voir §7) ; validation sur bases de test ;
retour arrière en lecture via `DROP COLUMN mode` (SQLite ≥ 3.35, sans perte).
2 e-dits : keys extraits explicitement (le split SQL du 1er jet coupait le
COALESCE → corrigé avant toute exécution utile).

**Source du mode = état RÉEL du feed** (`runtime.py`) : `--offline` explicite ou
bascule du feed (mode check à chaque tick) · jamais inféré du nom de processus.
Le JSONL trade porte aussi `payload.mode`.

**Stats protégées** (`tools/report_week.py`) : `--mode operational` (défaut :
exclut offline/test), `--mode all` (tout, étiqueté), `--mode offline` (démo seule),
+ ligne de provenance par comptes ; ancien schéma (sans colonne) annoncé
explicitement (« none (ancien schéma) ») — jamais de mélange silencieux.

**Tests ajoutés** — `tests/test_session_modes.py`, 7 tests : étiquetage live/offline
· migration sur DB historique (2 rows ancien schéma → conservées, 'unknown', PnL
intacts, cohabitation avec nouveau) · restauration après migration (trade SQLite
restauré, aucune duplication) · stats opérationnelles excluent la démo (+10.99 $
→ +1.00 $ re-stats par mode) · ancien schéma sans crash · mode suit l'état réel
du feed (bascule testée) · le JSONL porte le mode.
**2 échecs honnêtement diagnostiqués en cours de route** : mes attentes testaient
des lignes que le rapport n'imprime jamais (symboles) — vérifié manuellement les
sorties des 3 périmètres, assertions réécrites sur la réalité, code report inchangé
sur le fond (un espace de formatage corrigé + clés SQL du 1er jet corrigées avant
exécution utile).

Suite complète : **72 passed in 18.53s**. Diff : store/runtime/report_week + tests
· aucune donnée trackée modifiée · `git diff --check` OK · scan secrets vide.
Migration de la DB réelle (aidesk.db) : SAUVEGARDE puis boot B5 au redémarrage
suivant du desk (lignes 12 trades historiques liront 'unknown', conservées).





## B6 — Nettoyage P2 contrôlé (A→F) — **2026-10-21** ✅

**A · broker.manage() + GATE_BY_FEATURES** : zéro référence dans le dépôt (grep à
l'exécution) → supprimés. Incident d'édition survenu et réglé honnêtement : un
oldString trop large a écrasé la tête de `target_price()` — inspecté (`sed`),
réparé ; diff final = suppression de `manage()` seule, contrat TP/SL re-testé
(`test_target_price_toujours_actif_apres_nettoyage`, vert).

**B · llm.py** : `urllib.request/error` (morts) supprimés ; constantes breaker
(`DEAD_AFTER=3, COOLDOWN_S=600, _FAIL`) remontées EN TÊTE de module avant usage
(l'audit signalait la déclaration après `critique()`). Protocole fournisseur
inchangé ; test dédié (`test_llm_module_imports_et_breaker_intacts`).

**C · SQLite/journaux** : **index additifs** créés (`idx_trades_ts_close`,
`idx_decisions_ts`, `CREATE INDEX IF NOT EXISTS` → appliqués à l'ouverture, testé
sur base héritée). **WAL : NON activé — décision documentée** : écrivain unique
(le desk), base ~94 Ko, lecteurs rares et ponctuels (report_week) ; le bénéfice
de concurrence ne justifie pas la complexité backup/checkpoint. À revoir si des
outils concurrents apparaissent ; test de restauration inclus. Rotation JSONL :
non implémentée (reportée, limites déclarées — pas une suppression).

**D · desk.yaml** : `universe.exchanges_fallback` désormais **câblé réel**
(`Settings.fallbacks` → `Feed(fallbacks=…)` ; défaut `CORE_EXCHANGES` si clé
absente ; tests wiring runtime). `radar.poll_seconds` et `research.checks` :
vérifiés NON consommés par le code → annotés « INFORMATIF, non consommé » dans le
yaml (conservés ; suppression laissée à un arbitrage utilisateur explicite).

**E · README/RUNBOOK** : comptes de tests corrigés (25 → **80**, le chiffre réel
de la suite) ; dépendances complétées (`pip install ccxt pyyaml fastapi uvicorn
openai httpx pytest`) ; RUNBOOK aligné.

**F · valorisation (MTM)** : `unrealized()` désormais **cohérent avec
`PaperBroker.settle()`** — prix de sortie = last×(1−slippage_bps), frais sur
proceeds (avant : frais seuls → ~5 bps optimistes). Distinction documentée en
docstring : **valorisation indicative** (MTM, snapshot/dashboard) ≠ **PnL
réalisé** (settle()/add_trade uniquement). Tests numériques : MTM ≡ cash du
settle au même last (tolérance 2e-4 = arrondi 4 décimales), aucune écriture de
PnL fantôme sur simple variation de ticker.

**Tests ajoutés** — `tests/test_b6_cleanup.py`, 8 tests (3 échecs initiaux
honnêtement diagnostiqués : seuils TP/SL calculés sur `ask`-entrée, tolérance
d'arrondi 1e-6 trop serrée vs `round(...,4)`, `_snapshot()` écrit sans retour ;
corrigés — assertions resserrées sur la réalité, code jamais affaibli).

Suite complète : **80 passed in 14.35s**. Diff : 8 fichiers, +28/−28 ·
`git diff --check` OK · scan secrets vide · aucune donnée trackée modifiée.
Restart desk prévu après commit (MTM + fallbacks + index en production).

### Vérification production B6 — **2026-10-21 21:4x**
Restart supervisé (watchdog+desk, PIDs par `ps` précis) : restore identique
pré/post (wallet $20.38, 2 positions AVAX/ETH, 14 trades, matrice rev 7).
Index `idx_trades_ts_close`/`idx_decisions_ts` créés sur la DB réelle ;
répartition modes : `live 1 · unknown 13` (aucune donnée réécrite).
Dashboard HTTP 200. Aucune donnée détruite ; backup pré-migration conservé
(`aidesk.db.bak-avant-B5`).

### Correction comptable — **2026-10-21 21:5x**
Le message du commit de snapshot `d5a7e10` indiquait « 9W/5L » : **FAUX**.
Vérité SQLite : 14 trades = **8W/6L**, PnL net réalisé **+0.3113 $**.
Historique poussé NON réécrit (jamais de force-push sur main) ; le présent
correctif fait foi. Le rapport final Phase B utilise les chiffres vérifiés.

---

# Phase C — Couche Solana en lecture seule — **2026-10-21** ✅

**Objectif** : transformer l'esquisse `SolanaDataProvider` (docs/DATA_FLOW.md:86)
en module réel **consommé** (leçon B6 : pas de code mort), lecture seule, mode
offline explicite, None ≠ 0, TTL de péremption, AUCUNE supposition GMGN.

**Nouveau** (`aidesk/market/solana.py`) :
- `Observation(name/ts/value/ok/note)` — provenance + epoch sur chaque donnée ;
  `age/stale/usable(now, ttl)` — même taxonomie que Features de B2 (inconnu si
  ts≤0 ; Périmé si âge>TTL ; le consommateur fixe le seuil) ;
- `RpcProvider` — adapter sur les primitives éprouvées de `whale.py` (RPC
  publics + clé gratuite optionnelle `AIDESK_RPC_URL`) ; dégradation en
  Observation ok=False (endpoint lourd refusé → ABSENT, jamais[]) ;
- `OfflineProvider` — zéro réseau, zéro valeur inventée ;
- `resolve_provider()` — offline explicite par argument ou `AIDESK_SOLANA=offline` ;
  défaut : RpcProvider.

**Wiring réel** : `whale.snapshot(..., provider=…)` … route TOUTES les sources
via le provider (verdicts et schéma de sortie identiques au chemin historique ;
sémantique legacy conservée exc. edge « liste vide réelle » → PARTIEL, plus sûr) ;
`tools/whale_scan.py --offline` active le mode explicite (vérifié : échec
instantané « mode offline explicite », zéro appel réseau).

**Guard lecture-seule** : test permanent sur les sources (aucun
sendTransaction/signTransaction/requestAirdrop/signer/keypair/privateKey).

**Tests ajoutés** — `tests/test_solana_provider.py`, 11 tests (TOUS mockés,
aucun réseau). 5 échecs initiaux diagnostiqués honnêtement : NOW de module figé
(age=0.0), signature boom(m) sans top, collision attribut/méthode `price` du
fake, répartition fausse (concentration coupée entre 20 porteurs → top10 = 50 %
du ciblé), attente PARTIEL impossible offline (offline lève WhaleError avant
tout — le PARTIEL vient du RPC léger OK + lourd refusé). Tests corrigés, code
inchangé sur le fond.

**Suite complète : 91 passed** (80 + 11). Diff : solana.py nouveau, whale.py
(+54/−20 trimming), whale_scan.py, DATA_FLOW.md. Aucune donnée trackée
modifiée · scan secrets vide · `git diff --check` OK · runtime/feed NON touchés
→ pas de redémarrage du desk requis (couche stable hors de la boucle tick).

**Non atteint en C** : la collecte whale LIVE avec les endpoints lourds reste
bloquée sur la clé gratuite `AIDESK_RPC_URL` (état inchangé ; le layer est prêt,
la clé activera le provider sans autre changement). Pas de GMGN (contrat).

---

# Phase E-2 / F-1 / D-résidu — **2026-10-21** ✅

**E-2 · `tools/verify_desk.py`** — réconciliation SQLite (r-o) ↔ state.json ↔ events
: correspondance trades (drift signalé), montants négatifs impossible, equity ≈
wallet+vault+mtm, positions corrompues, provenance modes (B5), queue JSONL
parseable, champs risk. Codes 0 OK / 1 avert / 2 fatal. 8 tests sur bases
synthétiques (jamais la prod). Diagnostic honnête en route : unpack SQL 4→2
(bug du code, corrigé), ledger.equity est une COURBE pas un scalaire (hypothèse
fausse adoptée trop vite — corrigée, le dernier point est lu).
Usage réel : code 0, 19 trades 11W/8L net +0.48, live 6 · unknown 13.

**F-1 · `tools/export_dataset.py`** — corpus déterministe (tri id), CSV +
manifeste (sha256 du fichier, rows, W/L, by_mode) ; avertissement explicite
« données PAPER expérimentales, aucune garantie ». DB ouverte en URI ro
(read-only strict testé). Ancien schéma sans colonne mode → substitué 'unknown'.
Dataset réel exporté : docs/data/exp/trades_20261021T2201.csv + manifeste
(committés = versionné par git). Bug d'appel CLI corrigé (sys.argv[0] passé).

**D-résidu · objections SKEPTIC structurées** — `_extract_objection` : schéma
JSON {"objection": <str>} tenté, champ extrait re-borné 160 c ; JSON sans champ
valide/" non-str sur objet → None ; pas de JSON / malformé → texte libre borné
(comportement B3 conservé). La sortie LLM reste 100 % NON FIABLE, jamais
décisionnelle. Fournisseur/prompt/config inchangés ; 4 tests. Verdict/agg
invariants (suite existante).

**Suite complète : 108 passed** (91 → 108). `runtime/feed` non touchés ;
diff/secret/`--check` clean. Restart desk requis (research.py), Restauration
vérifiée après commit.

---

# Phase B7 / E-2b — **2026-10-22** ✅

**Diagnostic — erratum d'annonce** : à 08:42 je déclare « desk figé » ; FAUX —
écart de 2 min avec le dernier tick, pas d'heures ; le thread était en
nanosleep normal. Confirmé vivant par ouverture de 2 ticks réels. Erratum
consigné : ne JAMAIS affirmer un figeage sans delta horaire récent calculé.

**Défaut B7-1 observable en production** : 2 échecs réseau ~07:2x → flip
offline MUET (aucun event) → random walk avec ts=now → radar B2 passe
(flaîchise? fraîchesse contournée) → **7 trades démo étiquetés 'offline'
(ids 24-30) sur la banque réelle** → recovery possible : `refresh()` ne
retente JAMAIS le réseau une fois flip : démo permanente sans restart
(feed offline de 07:2x à 08:57 malgré un réseau rétabli — BTC réel 81953).

**B7-1 · feed/runtime** — `Feed.explicit` distingue la démo CLI (--offline)
du flip réseau ; `refresh()` retente les VRAIS marchés à chaque cycle une
fois dégradé (ex vivant) ; balises d'événements `feed_degrade`/`feed_recover`
(fin du flip muet) ; desk dégradé autonome : ZÉRO nouvelle entrée (les
données sont inventées), gestion SL/TP + gel B4 maintenus ; démo explicite
reste pleine — c'est son rôle de test. 5 tests (rétablissement réel mocké,
porte, transitions, démo CLI). Suite complète 118.

**B7-2 · watchdog** — garde de fraîcheur : process vivant + state.json >
stale_s → terminate/kill → relance. Jusqu'ici un hang SPÉCULATIF était
indétectable (watchdog relance uniquement sur exit). Seuil défaut 900 s >
pierrier légitime: prévoir breaker 600 s ; poll 20 s ; lecture tolérante
(ne tue JAMAIS sur le doute). Fonction pure testée (4 cas).

**E-2b · invariant equity corrigé** : l' « equity ≠ wallet+vault+mtm » de ce
matin (0.03) était une erreur de MON outil : l'équité de la série est le
RÉALISÉ (start + Σ PnL) — l'invariant correct est wallet+vault+ENGAGÉ des
positions (22.76+0+7.58 = 30.34 exact ce matin) ; MTM flottant informatif
hors invariant. Test du cas production ajouté (code 0 avec position).

**Déploiement** : desk redémarré 08:57, restore complet vérifié (30 trades,
matrice rev 16), **feed_live dès le boot** (offline False), watchdog v2
(31199) actif, verify code 0. Dashboard 26678 inchangé.

**Porte 30 trades** : 30 trades TOTALS dont **23 opérationnels** (live 10 +
unknown 13) et 7 démo offline exclus — la porte reste jugée sur opérationnel:
**23/30**, 7 à mener. PnL net réalisé +0.43 $ (17W/13L, mélange démo incl.).
