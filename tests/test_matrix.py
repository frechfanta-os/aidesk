from __future__ import annotations

import pytest

from aidesk.config import Matrix


def test_clamp_never_exceeds_bounds():
    m = Matrix()
    m.tighten("test", min_vol_surprise=50.0, pass_threshold=2.0, min_momentum=9.0)
    assert m.min_vol_surprise <= Matrix._CLAMP["min_vol_surprise"][1]
    assert m.pass_threshold <= Matrix._CLAMP["pass_threshold"][1]
    assert m.min_momentum <= Matrix._CLAMP["min_momentum"][1]


def test_clamp_never_below_bounds():
    m = Matrix(revisions=0)
    m.tighten("bas", min_vol_surprise=-20.0, pass_threshold=-5.0)
    assert m.min_vol_surprise >= Matrix._CLAMP["min_vol_surprise"][0]
    assert m.pass_threshold >= Matrix._CLAMP["pass_threshold"][0]


def test_revisions_and_history():
    m = Matrix()
    before = m.min_momentum
    m.tighten("cause A", min_momentum=0.0002)
    assert m.revisions == 1
    assert m.history == [(1, "cause A")]
    assert m.min_momentum == pytest.approx(before + 0.0002)
