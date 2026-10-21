from __future__ import annotations

import pytest

from aidesk.config import Matrix, Settings
from aidesk.runtime import Desk
from aidesk.types import Features


@pytest.fixture()
def tmp_desk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                       # isolement complet
    s, m = Settings(), Matrix()
    return Desk(s, m, offline=True)


@pytest.fixture()
def fake_feats():
    return Features("T/USDT", 100.0, 99.99, 100.01, 10_000_000.0,
                    0.003, 0.02, 2.0, 1.0)


def test_restore_positions_et_wallet(tmp_desk, fake_feats):
    d = tmp_desk
    d.broker.buy(fake_feats, 7.5, "EXEC", "MEMORY")
    d._snapshot()
    d2 = Desk(d.s, d.m, offline=True)                 # nouveau Desk → doit restaurer
    assert "T/USDT" in d2.broker.open
    pos = d2.broker.open["T/USDT"]
    assert pos.entry == pytest.approx(d.broker.open["T/USDT"].entry)
    assert pos.qty == pytest.approx(d.broker.open["T/USDT"].qty)
    assert d2.ledger.wallet_usdt == pytest.approx(d.ledger.wallet_usdt)
    assert d2.broker.fees_paid == pytest.approx(d.broker.fees_paid)


def test_restore_trades_depuis_sqlite(tmp_desk, fake_feats):
    d = tmp_desk
    pos = d.broker.buy(fake_feats, 7.5, "EXEC", "MEMORY")
    t = d.broker.settle(fake_feats, pos, fake_feats.last, "TP")
    d.store.add_trade(t)          # le runtime écrit au store, pas le broker
    d._snapshot()
    d2 = Desk(d.s, d.m, offline=True)
    assert len(d2.ledger.trades) == 1
    assert d2.ledger.trades[0].symbol == "T/USDT"
    assert d2.ledger.trades[0].pnl == pytest.approx(t.pnl)
    # clôturé au dernier prix avec frais+slippage → pnl < 0 (honnête)
    assert t.pnl < 0 and d2.ledger.losses == 1 and d2.ledger.wins == 0


def test_restore_matrice_bornee(tmp_desk):
    d = tmp_desk
    d.m.tighten("serrage test", pass_threshold=0.008, min_vol_surprise=0.1)
    d._snapshot()
    m2 = Matrix()
    d2 = Desk(d.s, m2, offline=True)
    assert d2.m.pass_threshold == pytest.approx(d.m.pass_threshold)
    assert d2.m.min_vol_surprise == pytest.approx(d.m.min_vol_surprise)
    assert d2.m.revisions == d.m.revisions


def test_restore_sans_state_ne_planterait_pas(tmp_desk):
    d = Desk(Settings(), Matrix(), offline=True)          # aucun state.json
    assert d.ledger.wallet_usdt == pytest.approx(30.0)


def test_force_close_ecrit_le_trade_en_sqlite(tmp_desk):
    d = tmp_desk
    fake = Features("Z/USDT", 100.0, 99.99, 100.01, 10_000_000.0,
                    0.003, 0.02, 2.0, 1.0)
    d.broker.buy(fake, 7.5, "EXEC", "MEMORY")
    d.last_feats["Z/USDT"] = fake                          # prix dispo pour la clôture
    d._force_close_all("KILL")
    rows = d.store.conn.execute("SELECT count(*) FROM trades").fetchone()[0]
    assert rows == 1                                       # regression : add_trade au KILL
    d2 = Desk(d.s, d.m, offline=True)
    assert len(d2.ledger.trades) == 1                      # restauré via SQLite
