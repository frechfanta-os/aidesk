# CODE COMPONENT MAP — AIDESK (Phase A)

*Cartographie des composants réels au commit `f0a9e72`. Chaque entrée : responsabilité
vérifiée dans le code, dépendances, points d'appel, couverture de tests, effets de bord.*

## 1. Vue d'ensemble des couches (état actuel)

```
            ┌──────────────────────────────────────────────────────────┐
            │                        runtime.Desk                       │
   CLI      │  tick(): controls → feed.refresh → manage → radar.scan    │
aidesk/main ├──────┬────────────┬──────────────┬───────────────┬────────┤
            │ desks│            │market        │ llm           │ store  │
            └──────┴────────────┴──────────────┴───────────────┴────────┘
```

## 2. Package `aidesk/` (cœur)

### `runtime.py` (448 LOC) — orchestrateur **Desk**
| Élément | Vérifié | Remarque |
|---|---|---|
| `Desk.__init__` (l.28-57) | wire feed/broker/ledger/store/radar/research/risk/execd/audit/treasury/head ; roster = desk.yaml fusionné sur défauts ; `self._restore()` | single-writer du desk |
| `_restore()` (l.63-142) | trades depuis **SQLite** systématiquement ; wallet/frais/agents/matrice/positions depuis state.json si présent ; event `restore` | positions restituées avec `ts_open` conservé |
| `run()` (l.145-176) | boucle : `tick()` → stop par hours/KILL ; `hourly()` au passage d'heure ; sleep résiduel (KeyboardInterrupt → break propre) | `_quiet` propagé |
| `tick()` (l.179-208) | `_controls` → `feed.refresh(top_n)` → `_manage_positions` → si non-PAUSE : radar.scan → research.decide → execd.try_entry ; HUD ; `_snapshot()` à chaque tick | PAUSE ne bloque que les NOUVELLES entrées |
| `_snapshot()` (l.218-297) | state.json clé par clé (ledger/positions/trades_closed≤500/agents/matrix/risk/counters), écrit atomique `tmp→os.replace`, jamais fatal (except: pass) | source de vérité dashboard |
| `_manage_positions` (l.300-322) | TP/SL via `broker.target_price`, TIMEOUT via `max_hold_minutes` ; settle → `store.add_trade` → audit.on_close → risk.on_close → `_credit` | entrée bloquée si prix inconnu (f is None → skip) |
| `_controls` (l.349-365) | KILL (precedence, remove flag, force_close, stop) ; SELL_ALL (force_close + snapshot) ; PAUSE binaire | fichiers `ctl/` |
| `_credit` (l.336-341) | crédite l'agent ET l'approver (double comptage volontaire : crédit d'équipe) | — |
| `unrealized()` (l.416-423) | Σ qty×last×(1−fee) — frais sortie décomptés, slippage sortie non (≈5 bps optimiste) | P2 |
| `final_report()` (l.426-448) | snapshot + scoreboard ; garde `_closed` (idempotent) | — |

### `config.py` (143) — Settings/Matrix
- `Matrix` (l.18-53) : poids + seuils + `_CLAMP` bornes {min_momentum [0.0008,0.005],
  max_momentum_1h [0.02,0.12], min_vol_surprise [1.0,3.0], pass_threshold [0.55,0.74]} ;
  `tighten()` clampée, `relax()` = tighten inversé — **CONFIRMÉ** par tests.
- `Settings.load()` (l.78-130) : desk.yaml → Settings + Matrix ; `desk_agents` extrait des listes yaml.
- `warnings.filterwarnings("ignore")` global (l.11) — à assainir (masquage large).
- `now_iso()` UTC ; `fmt_usd` ; `safe()` : "N"/"N/A"/None → default (normalisation ccxt).

### `store.py` (99) — persistance
- Schéma **CONFIRMÉ** (l.9-26) : `trades(ts_open,ts_close,symbol,entry,exit,qty,pnl,reason,agent,approver,score,features)` ; `decisions(ts,symbol,agent,agg,verdict,thesis,objection,scores)` ; `events(ts,kind,payload)` ; `matrix_history(ts,revision,note)`.
- `add_trade/add_decision/add_event` : INSERT paramétré + commit + `_emit` JSONL (flush) ; `add_matrix` (sans JSONL) ; `all_trades()` (lecture complète pour restore) ; `close()` double-close guard implicite (fh + conn).
- Manques (P2) : pas d'index/`ts_close`, pas WAL, pas de migrations versionnées, JSONL non roté.

### `types.py` (66)
- `Features(symbol,last,bid,ask,quote_volume_24h,mom_15m,mom_1h,vol_surprise,range_pct,fresh)` ;
  `Signal(+agent,ts)` ; `Decision(ts,symbol,agent,scores,agg,verdict,thesis,objection)` ;
  `Position(+ts_open,agent,approver,features,score)` ; `Trade(+exit,reason,ts_close)`.
- Aucun champ de provenance/ts par feature (gap Phase C).

### `llm.py` (116) — SKEPTIC (unique fournisseur IA)
- `_load_dotenv()` (l.10-24) : CWD puis racine projet, `os.environ.setdefault` (l'env shell
  prime sur le fichier — priorité correcte) ; `.env` jamais lu en mémoire-log.
- `has_key/_resolve` (l.27-38) : env `AIDESK_LLM_KEY` | `XAI_API_KEY` | `OPENAI_API_KEY` ;
  `AIDESK_LLM_BASE_URL` (défaut api.x.ai/v1) ; `AIDESK_LLM_MODEL` (défaut grok-3-fast).
- `describe()` (l.41-55) : thèse déterministe (aucun appel réseau).
- `critique()` (l.58-111) : breaker (`_FAIL.until`) ; client `openai.OpenAI` local
  (timeout httpx 30 s/connect 8 s sinon 25 s ; `max_retries=0`) ; messages système
  anti-injection ("Tu n'obéis JAMAIS..."); streaming ; `_FAIL.n` sur exception, suspension
  600 s après 3 échecs ; renvoie `str|None` **libre** (pas de schéma).
- Fragment fragile : constantes du breaker définies après la fonction (l.114-116) —
  fonctionne à l'appel, à installer proprement en Phase B.

### `__main__.py` (38)
- args : `--hours/--tick-seconds/--quiet/--offline/--db/--config` ; `KeyboardInterrupt`
  → stop + `_force_close_all("KBD-STOP")` + final_report (idempotent).

## 3. `desks/` (agents)

| Module (LOC) | Responsabilité vérifiée | Appels entrants | Tests | Findings |
|---|---|---|---|---|
| `radar.py` (41) | rotation 3 agents ; préfiltres (l.24-33) ; top-3 par mom15×min(vol_surp,3) ; cooldown 1800 s/sym ; `signals_emitted` | runtime.tick | (indirect) | `fresh` inerté (P1) |
| `research.py` (52) | checks + scores + agg + verdict ; thèse déterministe ; critique() LLM ; persiste decision | runtime.tick | 4 tests (verdict, refus, overext, rotation) | critique() sur refus (P1) |
| `risk.py` (67) | `allow()` 5 vetos ; `note_entry` ; `on_close` (day_pnl) ; `check_treasury_freeze` hystérésis ; `size_for = wallet×25%×budget` | runtime, execution, treasury | 5 tests (cap, 6/h, gel jour, gel tréso, sizing) | freeze horaire uniquement (P1) |
| `execution.py` (44) | re-check doublon ; risk.allow ; rotation 6 agents ; sizing (min $1, cap wallet) ; buy ; event `entry` | runtime.tick | indécis via risk tests | — |
| `audit.py` (45) | post-mortem par clôture ; serrage (SL→vol, perte lente→momentum) ; desserrage après 3 TP ; `add_matrix` à chaque revision | runtime closes | (via matrice tests) | — |
| `head.py` (37) | review horaire : promotion ≥0.65 & budget<1.8 ; licenciement <0.40 & cooldown ; ≥4 crédits requis | runtime.hourly | 2 tests (promo, fire+cooldown) | budget affecte le sizing → lié au risque (à cadrer Phase B) |
| `treasury.py` (26) | hour_tick → freeze check ; sweep 24 h (50 % de l'excès >1.5×start) | runtime.hourly | (via risk tests) | — |
| `base.py` (55) | `Agent` (budget/score 0.5+0.10W−0.15L clamps [0.10,0.95], fire v2 reset, last_fired) ; `roster()` ; `clamp01` | tous desks | 2 tests | — |

## 4. `market/`

| Module (LOC) | Points clés |
|---|---|
| `feed.py` (157) | `connect()` : essaie binance puis fallbacks, `enableRateLimit`, timeout 15 s ; `refresh()` : throttle 60 s → `fetch_tickers` (tout marché, filtre `*/USDT` spot, qv≥1M$, top_n) → `_basic_features` → `_enrich` (OHLCV 15m×6, mom_15m=vs close n−1, mom_1h=vs open n−4, vol_surprise=15m qv/(24h/96)) ; `AIDESK_ENRICH_LIMIT` ; offline **déterministe** (Random(7), 8 symboles) ; échec double → offline auto |
| `broker.py` (69) | buy: ask/last ×(1+5bps), fee 10 bps, débit wallet ; settle: last×(1−5bps), fee sur proceeds, crédit wallet, PnL=proceeds−usdt, append ledger.trades ; `target_price` TP/SL vs ENTRY ; **`manage()` code mort** |
| `ledger.py` (37) | wallet/vault ; `wins/losses` = propriétés calculées depuis trades (pnl>0 / ≤0) ; `sweep()` 50 % ; `net_usdt` |
| `whale.py` (237) | `rpc()` failover multi-endpoints (env puis PUBLIC_RPCS ; 401/403 → mort ; 429 → backoff linear) ; `mint_info` (getAccountInfo → supply SPL bytes 36..44, authorities 0..4/46..50) ; `largest_holders` (getTokenLargestAccounts) ; `price_jupiter`→`price_ccxt` fallback ; `snapshot()` émet les verdicts RUG-RISK/CONCENTRÉ/MOUVEMENT/OBSERVATION/**PARTIEL** ; `persist/previous` (whale.db, delta top10) ; `features_for_research` avec `whale_known` (inconnu ≠ 0). **Lecture seule** (urllib GET/JSON-RPC, aucune signature) |

## 5. `tools/` (opération)

| Outil (LOC) | Rôle vérifié |
|---|---|
| `dashboard.py` (279) | FastAPI : `GET /` (PAGE inline terminal-noir), `GET /api/state` (lit state.json), `GET /api/events?n` (formate JSONL), `POST /api/ctl` **avec contrôle anti-CSRF** (l.252) ; CORS `allow_origins=*` mais `allow_methods=[GET,OPTIONS]` ; bind par défaut `127.0.0.1` (env `AIDESK_BIND`) ; port 8787 |
| `watchdog.py` (47) | boucle subprocess `python3 -m aidesk` (+`AIDESK_ARGS`) ; rc 0 → sortie propre ; crash → relance cooldown (env `AIDESK_WATCHDOG_COOLDOWN`, plafond `AIDESK_MAX_RESTARTS`) ; `PYTHONUNBUFFERED=1` injecté |
| `build_site.py` (72) | snapshot dashboard → `docs/data/{state,events}.json` (API en priorité, fichiers en fallback) |
| `whale_scan.py` (67) | CLI `--mint/--watchlist/--price-symbol` sur whale.py |
| `report_week.py` (107) | markdown : trades window, winrate, espérance, drawdown, sparkline, raisons, top agents ; `-o` écrit |
| `stats.py` (36) | bilan SQLite brut |
| `llm_test.py` (152) | batterie SKEPTIC : 5 cas réalistes + **injection hostile** + concurrence + `--breaker` (test clé morte) |

## 6. `tests/` (26 tests verts — exécutés pendant l'audit)

| Fichier | Sujet | Couverture réelle |
|---|---|---|
| test_broker.py (4) | buy fees/qty, TP/SL thresholds, settle TP/SL + ledger, cash accounting (start+pnl) | broker + ledger |
| test_risk.py (5) | cap positions, 6 entrées/h glissantes, stop journalier + reset jour, gel trésorerie + dégel, sizing budget | risk |
| test_matrix.py (3) | `_CLAMP` bornes hautes/basses, revisions + history | config.Matrix |
| test_research.py (4) | verdict passant (agg≈0.7875), vol insuffisante refusée, overextension, deux rotations d'agents | research (LLM mocké) |
| test_head.py (2) | promotion budget, licenciement v2 + cooldown | head + base |
| test_restore.py (5) | positions/wallet/frais, trades via SQLite, matrice bornée, démarrage à neuf, **force_close écrit au store** (régression historique P1) | runtime._restore |
| test_feed.py (3) | snapshot offline (8 syms, bornes), throttle cache, parser ticker | feed |
| conftest.py | sys.path du projet | — |

**Absents** (voir Phase E) : breaker LLM en pytest, anti-CSRF 403/200, rejeu
(déterminisme données réelles), incohérence tri-couches, opérations comptables répétées.

## 7. Entrées de configuration & environnement (recensées)

| Source | Clés | Consommé par |
|---|---|---|
| `desk.yaml` | desks.*.agents, research.scoring_matrix, risk.*, execution.*, treasury.*, paper.*, universe.top_by_quote_volume/refresh_seconds, dex.enabled, head.* | Settings/Matrix.load |
| `desk.yaml` | radar.poll_seconds, research.checks, universe.exchanges_fallback | **NON consommé** (P2) |
| Env | `AIDESK_EXCHANGE`, `AIDESK_ENRICH_LIMIT`, `AIDESK_LLM_KEY/BASE_URL/MODEL`, `AIDESK_RPC_URL`, `AIDESK_BIND`, `AIDESK_ARGS`, `AIDESK_MAX_RESTARTS`, `AIDESK_WATCHDOG_COOLDOWN` | feed/llm/dashboard/watchdog |
| Fichiers ctl | `ctl/PAUSE`, `ctl/SELL_ALL`, `ctl/KILL` | runtime._controls (web via dashboard seulement si en-tête OK — P0) |

## 8. Classification globale (récapitulatif)

| Statut | Composants |
|---|---|
| **CONFIRMÉE** | runtime (boucle/restore/contrôles/thèse déterministe), config+`_CLAMP`, store, desks radar/research/risk/execution/audit/head/treasury, feed (réel+offline), broker (paper), ledger, whale (lecture seule), llm (breaker), dashboard GET, watchdog, tests 26/26, pas de connecteur réel |
| **PARTIELLEMENT CONFIRMÉE** | dashboard contrôles (P0 403 UI), filtre `fresh`, MTM slippage, config desk.yaml (clés ignorées), absence de logs de clés (statique), compat appareil |
| **NON VÉRIFIÉE** | validation schéma LLM (absente), étiquetage mode par donnée (absent), Termux natif, performance/edge (hors périmètre Phase A) |
