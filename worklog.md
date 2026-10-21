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
