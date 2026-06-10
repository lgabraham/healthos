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


def test_rolling_average_is_calendar_aware_across_gaps():
    """With per-day entries (None on gap days), a reading from before a long
    gap must not leak into the average after it, and sparse windows yield
    rolling=None rather than a fake average."""
    from datetime import date, timedelta

    base = date(2026, 5, 1)
    # 5 readings of 100, a 10-day gap, then 5 readings of 50.
    series = []
    for i in range(20):
        if i < 5:
            v = 100.0
        elif i < 15:
            v = None
        else:
            v = 50.0
        series.append((base + timedelta(days=i), v))
    out = rolling_average(series, window=7)
    # Mid-gap (day 13): only None in the trailing 7 days -> no rolling value.
    assert out[13]["rolling"] is None
    # After the gap (day 19): trailing window holds only the 50s — no 100s.
    assert out[19]["rolling"] == 50.0
