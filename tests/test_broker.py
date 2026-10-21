from __future__ import annotations

import os

import pytest

from aidesk.config import Settings
from aidesk.market.broker import PaperBroker
from aidesk.market.ledger import Ledger
from aidesk.types import Features


@pytest.fixture()
def broker_env():
    s = Settings()
    l = Ledger(s.start_usdt)
    b = PaperBroker(l, s)
    return s, l, b


@pytest.fixture()
def features():
    return Features("X/USDT", 100.0, 99.99, 100.01, 10_000_000.0,
                    0.003, 0.02, 2.0, 1.0)


def test_buy_deducts_wallet_with_fees(broker_env, features):
    s, l, b = broker_env
    pos = b.buy(features, 7.5, "EXEC", "MEMORY")
    assert l.wallet_usdt == pytest.approx(22.5)
    expected_price = 100.01 * (1 + s.slippage_bps / 10_000)
    assert pos.entry == pytest.approx(expected_price)
    fee = 7.5 * s.fee_bps / 10_000
    assert pos.qty == pytest.approx((7.5 - fee) / expected_price)
    assert b.open["X/USDT"] is pos
    assert b.fees_paid == pytest.approx(fee)


def test_target_price_hits_tp_then_sl(broker_env, features):
    s, _, b = broker_env
    b.buy(features, 7.5, "EXEC", "MEMORY")
    tp = b.target_price("X/USDT", 102.0)
    assert tp is not None and tp[0] == "TP"
    assert b.target_price("X/USDT", 100.05) is None      # zone morte
    assert b.target_price("X/USDT", 99.0)[0] == "SL"
    assert b.target_price("Y/USDT", 100) is None          # pas de position


def test_settle_credits_wallet_with_fees(broker_env, features):
    s, l, b = broker_env
    pre = l.wallet_usdt
    pos = b.buy(features, 7.5, "EXEC", "MEMORY")
    trade = b.settle(features, pos, 102.0, "TP")
    assert trade.pnl > 0
    assert trade.reason == "TP"
    assert "X/USDT" not in b.open
    assert l.wallet_usdt > pre            # TP net de frais → bénéfice
    assert l.wins == 1 and l.losses == 0


def test_settle_loss_and_trades_ledger(broker_env, features):
    s, l, b = broker_env
    pos = b.buy(features, 7.5, "EXEC", "MEMORY")
    trade = b.settle(features, pos, 99.0, "SL")
    assert trade.pnl < 0
    assert l.losses == 1 and l.wins == 0
    # comptabilité cash : achat débite, vente recrédite → net = start + pnl
    assert l.wallet_usdt == pytest.approx(s.start_usdt + trade.pnl)
