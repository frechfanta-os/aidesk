# DATA FLOW — AIDESK (Phase A)

*Flux de données vérifiés au commit `f0a9e72` : provenance, transformations, stockages,
modes dégradés. Rien n'est inféré de la documentation — chaque flèche est ancrée à un code.*

## 1. Flux d'un tick (60 s nominal)

```
[1] ctl/PAUSE|SELL_ALL|KILL ──fichiers──▶ runtime._controls (l.349)   (inspectés chaque tick)
[2] ccxt.fetch_tickers(exchange) ─▶ feed.refresh (l.50)             │
        filtre */USDT spot, qv≥1 M$, top_n=40                       │
[3] pour chaque sym du top : _basic_features (l.103)                │
        then _enrich: fetch_ohlcv("15m", limit=6) (l.124)           ▼
        mom_15m = (last − close[n−1])/close[n−1]
        mom_1h  = (last − open[n−4])/open[n−4]
        vol_surprise = (qvol_15m×last)/(qv_24h/96)
[4] features (dict sym→Features) ─▶ last_feats.update (l.185)       cache global
[5] _manage_positions: TP(+1.2%)/SL(−0.8%)/TIMEOUT(90 min)          via target_price
        └─ settle → store.add_trade → audit.on_close → risk.on_close → _credit
[6] si !paused: radar.scan (préfiltres, cooldown 1800 s, top-3)
        └─ Signal ─▶ research.decide (checks/scores/agg → verdict → thèse ≙ llm.describe)
              ├─ llm.critique (SKEPTIC, synchron, breaker 3×→600 s) ──▶ objection (texte)
              └─ store.add_decision (thesis+objection si verdict)
        └─ si verdict: execution.try_entry
              ├─ risk.allow (5 vetos) ─┤ bloqué → event risk_block
              └─ broker.buy (frais+slippage) → event entry
[7] HUD console (si !quiet) ─▶ _snapshot() ─▶ state.json (atomique)
```

## 2. Provenance et qualité par famille de données

| Donnée | Source | Transformation | Qualité/provenance actuelle | Classement |
|---|---|---|---|---|
| tickers (top 40) | ccxt public (binance→bybit→okx→kraken→gate) | filtre spot/qv | aucun ts par feature ; `fresh` inerté ; `quoteVolume==None→0` via `safe()` ; pas de détection de régime | PARTIELLEMENT CONFIRMÉE |
| OHLCV 15m | même exchange, `fetch_ohlcv` limit=6 | différences closes/opens | échec silencieux → mom15=0/vol_surp=1.0 (**valeur par défaut indistinguable d'une vraie valeur**) → rejeté par préfiltre (sûr mais muet) | PARTIELLEMENT CONFIRMÉE |
| wallet/fees/pnl | PaperBroker (interne) | cash accounting | recalculable à 100 % depuis trades (prouvé par tests) | CONFIRMÉE |
| decisions/objections | research (déterministe) + llm (libre) | INSERT + JSONL | texte LLM **non validé** (aucun schéma) ; latence sync | PARTIELLEMENT CONFIRMÉE |
| events | events/entry/trade/risk_block/postmortem/head_review/sweep/restore/boot | JSONL append-only | non roté ; payload libre (dict) | CONFIRMÉE (mécanique) |
| whales Solana | RPC publics (JSON-RPC) + Jupiter API | offsets SPL (supply l.36..44 ; authorités 0..4/46..50) | `top10_pct=None` si endpoint lourd refusé (**None ≠ 0** respecté via `whale_known`) ; verdict PARTIEL ; ts persisté (whale.db) | CONFIRMÉE (dégradée maîtrisée) |
| state.json | Desk (recalcul du tout) | snapshot complet | atomique ; contient `feed.offline` (étiquette démo à ce niveau) | CONFIRMÉE |

## 3. Stockages — schémas et invariants vérifiés

### SQLite `aidesk.db` (store.py:9-26)
- `trades` : 12 colonnes + id autoincr — écrit par `add_trade` (chaque clôture, P1 régression fixed) ;
- `decisions` : chaque verdict research (`add_decision`) ;
- `events` : kinds vus — boot, entry, trade, decision, risk_block, postmortem, head_review, sweep, restore ;
- `matrix_history` : chaque revision audité ;
- **Pas d'index**, pas WAL, pas de migration versionnée (CREATE IF NOT EXISTS) — P2.
- Restauration : `all_trades()` → ledger.trades (source de vérité trades).

### `state.json` (runtime._snapshot, l.218-297)
Clés : `ts, ticks, paused, feed{offline,name}, ledger{start,wallet,vault,fees,mtm,wins,losses,equity[...]}, positions[{symbol,entry,qty,usdt,agent,approver,score,ts_open,age_min,last}], trades_closed[≤500], agents[14], matrix, risk{blocks,day_pnl,day_frozen,frozen_treasury}, counters`.
- Écriture atomique (`tmp`+`os.replace`), jamais bloquante (except: pass) ;
- C'est **la seule interface du dashboard** (`/api/state` lit ce fichier tel quel).

### `events.jsonl`
- Append + flush à chaque `_emit` ; ligne = {ts,kind,payload} ; consommé par `/api/events` (erreurs ignorées ligne par ligne) et build_site.py.

### `whale.db`
- (mint, ts, top10_pct, ...) — `previous()` lit la dernière ligne pour delta top10.

## 4. Propagation des contrôles humains

| Contrôle | Chemin | Effet vérifié |
|---|---|---|
| `ctl/KILL` (+bouton web — cassé P0) | _controls → _force_close_all("KILL") → store/audit/risk → stop=True → final_report | positions soldées au prix du marché paper ; watchdog sort (rc 0) |
| `ctl/SELL_ALL` | idem, desk continue + snapshot immédiat | — |
| `ctl/PAUSE` | _controls → self.paused → tick saute radar/exec | la gestion des positions ouvertes continue |
| dashboard `/api/ctl` | POST + en-tête `X-Requested-With: desk-ui` (sinon **403**) → touch fichiers ctl | la page actuelle ne pose pas l'en-tête → P0 |

## 5. Modes dégradés & étiquetage

| Mode | Déclencheur | Annonce | Marque de données | Risque |
|---|---|---|---|---|
| OFFLINE (démo) | `--offline` ou 2 échecs fetch_tickers | bannière + event `boot{mode}` + `feed.offline` | **non étiqueté dans trades/decisions** (P1) | contamination du corpus |
| whale PARTIEL | endpoint lourd 401/403/429 | verdict texte + `None` (pas 0) | persisté None | propre |
| SKEPTIC suspend | 3 échecs LLM | silence (compteur) ; outage impossible tuer le tick | objection=None | propre |
| LLM slow | timeout 30 s | — | tick ralenti jusqu'à ~30 s/decision (P1 latence sync) | à cadrer Phase B |

## 6. Phase C — couche de données Solana (conception proposée, sans implémentation)

Interface remplaçable (inspirée directe de whale.py existant) :

```
class SolanaDataProvider(Protocol):
    def mint_info(mint) -> MintInfo | None            # {source, ts, supply, authorities}
    def largest_holders(mint, top) -> list[Holders] | None   # None = endpoint lourd indisponible
    def price(mint) -> PriceInfo | None              # Jupiter (API documentée) puis CEX
    def watch(addresses) -> list[Balance]             # lecture seule
```

Contrats de qualité exigés (déjà partiellement implémentés dans whale.py) :
1. `Observation {name: str(source), ts: float(epoch UTC), value, ok: bool}` — chaque observation porte sa source ;
2. **None ≠ 0** — une valeur inconnue est `None` + flag ; jamais un 0 inventé (whale.py réglé, feed.py pas) ;
3. détection périmée : `ts_observation + TTL < now` → `stale=True` → **évaluations bloquées** (la feature whale/radar n'est pas utilisée) ;
4. contradictoires : deux sources disponibles → conserver la plus récente + journaliser l'écart ; sans fusion fantaisiste ;
5. qualité : RESEARCH reçoit `quality: A|B|C` et les observations de qualité C sont étiquetées « non-actionnable » ;
6. lecture seule : urllib GET/JSON-RPC ; aucune clé signée ; les endpoints sont uniquement des interfaces **publiques documentées** (RPC Solana, API Jupiter). **Aucune supposition GMGN** (pas d'appel à une API non documentée, non gratuite, non stable par preuve).

> **Implémentation (Phase C, 2026-10-21)** : `aidesk/market/solana.py` —
> `Observation` (source/ts/ok/TTL), `RpcProvider` (adapter sur les primitives de `whale.py`),
> `OfflineProvider` (absent ≠ 0), `resolve_provider()`. **Consommé** par
> `whale.snapshot(..., provider=…)` et le CLI `tools/whale_scan.py --offline` ; guard
> lecture-seule testé (`tests/test_solana_provider.py::test_guard_lecture_seule_sources`).

Adapters prévus (Phase C rénelle) : `RpcSolanaProvider` (whale.py wrapped), `HistoricalProvider` (dumps jsonl versionnés à disk), `CexPriceProvider` (ccxt déjà présent).

## 7. Cohérence tri-couches (statut)

- SQLite ↔ ledger.trades : `all_trades()` est la source des trades restaurés ; l'équité est recalculée `start + Σpnl` → cohérence **testée** (test_restore) ;
- state.json ← Desk snapshot : fidélité position-par-position vérifiée ad hoc (dashboard) ; pas de test pytest d'invariance génération/lecture (Phase E) ;
- dashboard ← state.json : lecture directe sans transformation — le seul mismatch identifié est le P0 (contrôles POST).

**Livrable de Phase A : flux déchiffré, trouvailles = 1 P0 (dashboard POST) + 3 P1 + un manque transversal (étiquette de provenance). Les schémas ci-dessus alimentent directement les Phases B (couches) et C (connecteur Solana).**
