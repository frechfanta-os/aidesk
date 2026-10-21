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

