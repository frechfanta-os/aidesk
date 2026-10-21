"""Tests B6 — nettoyage contrôlé : code mort, MTM indicatif cohérent (numérique),
index additifs, câblage des fallbacks d'exchange. Chaque test est exécutable,
jamais déclaratif."""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from aidesk.config import CORE_EXCHANGES, Matrix, Settings  # noqa: E402
from aidesk.market.broker import PaperBroker   # noqa: E402
from aidesk.market.feed import Feed            # noqa: E402
from aidesk.market.ledger import Ledger        # noqa: E402
from aidesk.runtime import Desk                # noqa: E402
from aidesk.store import Store                 # noqa: E402
from aidesk.types import Features              # noqa: E402


def feat(sym: str = "Y/USDT", last: float = 100.0) -> Features:
    return Features(sym, last, 99.9, 100.1, 6e6, 0.004, 0.02, 2.0, 0.5,
                    True, time.time())


# A — code mort supprimé sans casser les contrats --------------------------------

def test_manage_et_gate_supprimes():
    assert not hasattr(PaperBroker, "manage")
    assert not hasattr(PaperBroker, "GATE_BY_FEATURES")


def test_target_price_toujours_actif_apres_nettoyage():
    """Régression : le nettoyage du code mort n'a pas touché au contrat TP/SL."""
    led = Ledger(30.0)
    b = PaperBroker(led, Settings())
    f = Features("X/USDT", 100.0, None, None, 6e6, 0, 0, 1, 0, True, time.time())
    b.buy(f, 10.0, "EXEC", None)                         # ask=None → entry=100×(1+slip)
    assert b.target_price("X/USDT", 102.0)[0] == "TP"    # +1.95 % ≥ +1.2 %
    assert b.target_price("X/USDT", 99.0)[0] == "SL"     # −1.05 % ≤ −0.8 %
    assert b.target_price("X/USDT", 100.5) is None       # +0.45 % : ni TP ni SL


# B — llm.py : imports morts en moins, breaker inchangé ---------------------------

def test_llm_module_imports_et_breaker_intacts():
    import aidesk.llm as L
    src = Path(PROJECT / "aidesk" / "llm.py").read_text()
    assert "import urllib" not in src                    # imports morts supprimés
    assert L.DEAD_AFTER == 3 and L.COOLDOWN_S == 600.0   # politique inchangée
    assert L._FAIL == {"n": 0, "until": 0.0}


# F — MTM indicatif ≡ maths du PaperBroker.settle (numérique et vérifiable) -------

def test_unrealized_coherent_avec_settle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = Settings()                                       # fee 10 bps, slip 5 bps
    desk = Desk(s, Matrix(), offline=True, db_path="t.db", jsonl="t.jsonl")
    f_in = feat("Y/USDT", 100.0)
    pos = desk.broker.buy(f_in, 10.0, "EXEC", None)      # débit 10 $
    desk.last_feats["Y/USDT"] = feat("Y/USDT", 100.0)    # le last vaut exactement 100
    cash_attendu = pos.qty * 100.0 * (1 - s.slippage_bps / 10_000) \
        * (1 - s.fee_bps / 10_000)
    mtm = desk.unrealized()                              # valorisation indicative
    assert abs(mtm - cash_attendu) < 2e-4                # mtm arrondi à 4 décimales
    wallet_avant = desk.ledger.wallet_usdt               # 20.00 (30 − 10)
    trade = desk.broker.settle(desk.last_feats["Y/USDT"], pos, 100.0, "MTM-REF")
    # le CASH réel post-clôture au même last ≡ wallet_avant + mtm (cohérence du desk)
    assert abs(desk.ledger.wallet_usdt - (wallet_avant + mtm)) < 2e-4
    assert abs(trade.pnl - (cash_attendu - 10.0)) < 2e-4  # PnL réalisé cohérent
    assert "Y/USDT" not in desk.broker.open               # clôture consommée


def test_mtm_est_indicatif_et_non_le_pnl_realise(tmp_path, monkeypatch):
    """Le MTM cite le prix de sortie net ; le PnL réalisé ne vient que de settle."""
    monkeypatch.chdir(tmp_path)
    desk = Desk(Settings(), Matrix(), offline=True, db_path="t.db", jsonl="t.jsonl")
    pos = desk.broker.buy(feat("Z/USDT", 100.0), 10.0, "EXEC", None)
    desk._snapshot()
    snap = json.loads(Path("state.json").read_text())    # _snapshot écrit, ne retourne rien
    assert snap["ledger"]["mtm_usdt"] > 0                # valorisation indicative
    assert desk.ledger.trades == []                      # réalisée : aucune
    desk.last_feats["Z/USDT"] = feat("Z/USDT", 101.0)    # le ticker monte
    desk._snapshot()
    assert desk.ledger.trades == []                      # pas de PnL fantôme


# C — index additifs sur une base héritée ------------------------------------------

def test_index_additifs_et_migration(tmp_path):
    p = tmp_path / "legacy.db"
    con = sqlite3.connect(str(p))
    con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "ts_close REAL)")                        # base héritée minimale
    con.commit()
    con.close()
    st = Store(str(p), str(tmp_path / "t.jsonl"))        # ouverture = SCHEMA+migration
    idx = {r[1] for r in st.conn.execute("PRAGMA index_list(trades)")}
    assert "idx_trades_ts_close" in idx
    idx_d = {r[1] for r in st.conn.execute("PRAGMA index_list(decisions)")}
    assert "idx_decisions_ts" in idx_d
    cols = {r[1] for r in st.conn.execute("PRAGMA table_info(trades)")}
    assert "mode" in cols                               # B5 toujours en place
    st.close()


# D — fallbacks d'exchange câblés depuis desk.yaml ----------------------------------

def test_fallbacks_cables_depuis_yaml(tmp_path, monkeypatch):
    cfg = tmp_path / "d.yaml"
    cfg.write_text("universe:\n  exchanges_fallback: [bybit, kraken]\n",
                   encoding="utf-8")
    s, m = Settings.load(str(cfg))
    assert s.fallbacks == ["bybit", "kraken"]
    monkeypatch.chdir(tmp_path)
    d = Desk(s, m, offline=True, db_path="t.db", jsonl="t.jsonl")
    assert d.feed.fallbacks == ["bybit", "kraken"]       # wiring runtime réel


def test_fallbacks_defaut_sans_yaml():
    s, _ = Settings.load(str("/chemin/sans/yaml/inexistant"))   # défauts dataclass
    assert s.fallbacks is None
    f = Feed(offline=True)
    assert f.fallbacks == CORE_EXCHANGES                 # repli conservé
