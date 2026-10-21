from __future__ import annotations

import pytest

from aidesk.market.feed import Feed


def test_offline_snapshot_shape_and_ranges():
    f = Feed(offline=True)
    feats = f.refresh(40, min_interval=0)
    assert len(feats) == 8
    for sym, x in feats.items():
        assert sym.endswith("/USDT")
        assert x.last > 0
        assert 0.4 < x.vol_surprise < 3.6
        assert x.quote_volume_24h >= 3e6


def test_refresh_throttle_returns_cache():
    f = Feed(offline=True)
    a = f.refresh(40, min_interval=1_000_000)
    b = f.refresh(40, min_interval=1_000_000)
    assert a is b


def test_basic_features_from_ticker():
    f = Feed(offline=True)
    fx = f.features_from_ticker("BTC/USDT", {"last": "82000.5", "quoteVolume": 1.2e9,
                                             "percentage": 1.5, "high": 82100,
                                             "low": 81800, "bid": 82000.4,
                                             "ask": 82000.6})
    assert fx.last == 82000.5
    assert fx.mom_1h == pytest.approx(0.015)
