"""Re-flag is_canonical on existing rows after a canonical-source rule change.

The is_canonical column is set at insert time, so changing CANONICAL_METRIC_SOURCE
(or the sleep-session source) only affects NEW data. Run this once to bring
historical daily_metrics + sleep_sessions in line with the current rules.

    python scripts/reflag_canonical.py
"""
from __future__ import annotations

from sqlalchemy import select, update

from healthos.canonical import is_canonical_metric, is_canonical_sleep
from healthos.database import SessionLocal
from healthos.models import DailyMetric, SleepSession


def main() -> None:
    s = SessionLocal()
    try:
        metric_rows = s.execute(
            select(DailyMetric.metric, DailyMetric.source).distinct()
        ).all()
        for metric, source in metric_rows:
            s.execute(
                update(DailyMetric)
                .where(DailyMetric.metric == metric, DailyMetric.source == source)
                .values(is_canonical=is_canonical_metric(metric, source))
            )

        for (source,) in s.execute(select(SleepSession.source).distinct()).all():
            s.execute(
                update(SleepSession)
                .where(SleepSession.source == source)
                .values(is_canonical=is_canonical_sleep(source))
            )
        s.commit()
        print(f"Re-flagged {len(metric_rows)} (metric, source) combos + sleep sessions.")
    finally:
        s.close()


if __name__ == "__main__":
    main()
