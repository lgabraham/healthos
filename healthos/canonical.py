"""Canonical-source rules.

When multiple devices report the same logical metric we store all of them but
flag exactly one row as canonical. The mapping below is the single source of
truth for which device wins each metric, derived from the project spec.
"""

from __future__ import annotations

# Sources -------------------------------------------------------------------
WHOOP = "whoop"
GARMIN = "garmin"
EIGHT_SLEEP = "eight_sleep"
APPLE_HEALTH = "apple_health"  # pushed from the phone via the iOS Shortcut

ALL_SOURCES = (WHOOP, GARMIN, EIGHT_SLEEP)

# Per-metric canonical source. Keys are the normalized ``metric`` strings used
# in daily_metrics; values are the winning source.
CANONICAL_METRIC_SOURCE: dict[str, str] = {
    # Canonical = your PRIMARY device for each signal (what you actually wear),
    # not the theoretically-best instrument. You sleep on the Eight Sleep
    # nightly, so it owns the nightly cardiac/sleep signals; Whoop is the
    # labeled fallback for nights away from the pod (e.g. travel).
    "hrv_rmssd": EIGHT_SLEEP,
    "resting_hr": EIGHT_SLEEP,
    "sleep_duration_minutes": EIGHT_SLEEP,
    "rem_sleep_minutes": EIGHT_SLEEP,
    "deep_sleep_minutes": EIGHT_SLEEP,
    "light_sleep_minutes": EIGHT_SLEEP,
    "awake_minutes": EIGHT_SLEEP,
    # Whoop-only proprietary signals (no other source produces them).
    "recovery_score": WHOOP,
    "strain_score": WHOOP,
    "spo2": WHOOP,
    "respiratory_rate": WHOOP,
    # Garmin owns exercise + training-load + activity volume.
    "exercise_hr": GARMIN,
    "vo2_max": GARMIN,
    "training_load": GARMIN,
    "tss": GARMIN,
    "body_battery": GARMIN,
    "stress_avg": GARMIN,
    # Phone is carried everywhere, so it's the better step counter than a
    # sometimes-worn watch — Apple Health wins; Garmin steps become a fallback.
    "steps": APPLE_HEALTH,
    "workout_duration_minutes": GARMIN,
    # Eight Sleep owns the sleep *environment*.
    "bed_temp": EIGHT_SLEEP,
    "skin_temp": EIGHT_SLEEP,
    "room_temp": EIGHT_SLEEP,
    "toss_turn_count": EIGHT_SLEEP,
}

# Which source is canonical for whole sleep *sessions* (architecture/staging).
# The pod is the nightly device; Whoop covers away-from-pod nights as fallback.
CANONICAL_SLEEP_SESSION_SOURCE = EIGHT_SLEEP

# When several NON-canonical sources report the same metric on a day, pick the
# fallback deterministically so a re-sync never flips the displayed value. For
# the pod-canonical signals (HRV/RHR/sleep), this means an away-from-pod night
# falls back to Whoop before Garmin. (Canonical is chosen first, before this.)
FALLBACK_PRIORITY = (WHOOP, EIGHT_SLEEP, GARMIN, APPLE_HEALTH)


def source_rank(source: str) -> int:
    """Lower = preferred when breaking ties between fallback sources."""
    try:
        return FALLBACK_PRIORITY.index(source)
    except ValueError:
        return len(FALLBACK_PRIORITY)


def is_canonical_metric(metric: str, source: str) -> bool:
    """True if ``source`` is the canonical provider for ``metric``.

    Unknown metrics default to non-canonical so we never silently promote a
    metric we have not deliberately mapped.
    """
    return CANONICAL_METRIC_SOURCE.get(metric) == source


def is_canonical_sleep(source: str) -> bool:
    return source == CANONICAL_SLEEP_SESSION_SOURCE
