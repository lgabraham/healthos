"""One-time historical backfill across all three sources.

Pulls the trailing N days (default 90), then seeds behavioral inference over the
same window. Garmin is the rate-limit risk, so we backfill it in small chunks
with pauses between chunks; Whoop and Eight Sleep tolerate wider windows.

Usage:
    python -m scripts.backfill --days 90
    python scripts/backfill.py --days 90
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import date, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("backfill")

# Garmin: pull in 7-day chunks with a pause between chunks to stay polite.
GARMIN_CHUNK_DAYS = 7
GARMIN_CHUNK_PAUSE_SECONDS = 5.0


def run_backfill(days: int = 90) -> None:
    from healthos.database import get_session
    from healthos.inference.behavioral import run_inference_for_date
    from healthos.sync.runner import sync_source

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    log.info("Backfilling %s .. %s (%d days)", start, end, days)

    # Whoop + Eight Sleep handle the full window in one shot.
    for source in ("whoop", "eight_sleep"):
        result = sync_source(source, start, end, sync_type="backfill")
        log.info("%s: %s (%d records) %s", source, result.status, result.records_written,
                 "; ".join(result.errors))

    # Garmin: chunked + paced.
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=GARMIN_CHUNK_DAYS - 1), end)
        result = sync_source("garmin", chunk_start, chunk_end, sync_type="backfill")
        log.info("garmin %s..%s: %s (%d records) %s", chunk_start, chunk_end, result.status,
                 result.records_written, "; ".join(result.errors))
        chunk_start = chunk_end + timedelta(days=1)
        if chunk_start <= end:
            time.sleep(GARMIN_CHUNK_PAUSE_SECONDS)

    # Seed inference over the whole window.
    log.info("Seeding behavioral inference ...")
    with get_session() as session:
        day = start
        inferred = 0
        while day <= end:
            inferred += len(run_inference_for_date(session, day))
            day += timedelta(days=1)
    log.info("Backfill complete. Inferred %d events.", inferred)


def main() -> None:
    parser = argparse.ArgumentParser(description="HealthOS historical backfill")
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()
    run_backfill(days=args.days)


if __name__ == "__main__":
    main()
