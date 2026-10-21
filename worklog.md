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



