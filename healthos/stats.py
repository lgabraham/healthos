"""Tiny dependency-free statistics helpers (Pearson r, rolling average).

Kept out of numpy/pandas deliberately: the datasets here are single-user and
small, and avoiding the heavy deps keeps the MCP server and API lightweight.
"""

from __future__ import annotations

from math import sqrt


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation coefficient, or None if undefined."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    return cov / sqrt(vx * vy)


def rolling_average(series: list[tuple], window: int) -> list[dict]:
    """Rolling mean over (date, value) pairs. Emits {date, value, rolling}.

    Calendar-aware when the caller passes one entry per day with ``None`` for
    gap days (the trend endpoint does): the window slides over the trailing
    ``window`` *entries* and averages only the values present, so a reading
    from before a two-week gap can't leak into "this week's" average. The
    rolling value is None when fewer than ``max(1, window // 3)`` readings
    exist in the window — too sparse to call an average honestly.
    """
    out: list[dict] = []
    recent: list[float | None] = []
    min_present = max(1, window // 3)
    for d, v in series:
        recent.append(v)
        if len(recent) > window:
            recent.pop(0)
        present = [x for x in recent if x is not None]
        rolling = round(sum(present) / len(present), 2) if len(present) >= min_present else None
        out.append({"date": d.isoformat(), "value": v, "rolling": rolling})
    return out


def interpret_r(r: float | None, n: int) -> str:
    """Plain-language reading of a correlation, with sample-size caveats."""
    if r is None:
        return "Not enough overlapping data to estimate a relationship."
    strength = (
        "negligible"
        if abs(r) < 0.1
        else "weak"
        if abs(r) < 0.3
        else "moderate"
        if abs(r) < 0.5
        else "strong"
    )
    direction = "positive" if r > 0 else "negative"
    caveat = " (small sample — treat as suggestive only)" if n < 20 else ""
    return f"{strength.capitalize()} {direction} relationship (r={r:.2f}, n={n}){caveat}."
