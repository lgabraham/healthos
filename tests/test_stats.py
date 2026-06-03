"""Unit tests for the dependency-free stats helpers."""

from __future__ import annotations

from datetime import date

from healthos.stats import interpret_r, pearson, rolling_average


def test_pearson_perfect_positive():
    assert pearson([1, 2, 3], [2, 4, 6]) == 1.0


def test_pearson_perfect_negative():
    assert pearson([1, 2, 3], [6, 4, 2]) == -1.0


def test_pearson_undefined_on_constant():
    assert pearson([1, 1, 1], [2, 3, 4]) is None
    assert pearson([5], [5]) is None


def test_rolling_average_window():
    series = [(date(2026, 6, d), float(d)) for d in range(1, 5)]
    out = rolling_average(series, window=2)
    assert out[0]["rolling"] == 1.0
    assert out[1]["rolling"] == 1.5  # (1+2)/2
    assert out[3]["rolling"] == 3.5  # (3+4)/2


def test_interpret_flags_small_sample():
    msg = interpret_r(0.8, n=5)
    assert "small sample" in msg
    assert "strong positive" in msg.lower()
