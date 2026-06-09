"""HealthOS command-line interface.

    healthos init-db                 create tables (dev shortcut; prefer alembic)
    healthos setup                   interactive wizard to fill in .env credentials
    healthos whoop-auth              print the Whoop OAuth URL for first auth
    healthos doctor                  check which providers are connected
    healthos sync [--days N]         sync recent days for all sources
    healthos backfill [--days 90]    historical backfill (rate-limit friendly)
    healthos infer --start --end     re-run behavioral inference over a range
    healthos summary [--date]        print a day's canonical metrics
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta


def _cmd_init_db(_args: argparse.Namespace) -> None:
    from .database import Base, engine
    from . import models  # noqa: F401 - ensure models are registered

    Base.metadata.create_all(engine)
    print("Created all tables.")


def _cmd_setup(_args: argparse.Namespace) -> None:
    from .setup_wizard import run_wizard

    run_wizard()
    try:
        answer = input("Run `healthos doctor` now to verify? [Y/n] ").strip().lower()
    except EOFError:
        answer = "n"
    if answer in ("", "y", "yes"):
        _cmd_doctor(_args)


def _cmd_whoop_auth(_args: argparse.Namespace) -> None:
    from .sync.whoop import authorize_url

    print("Open this URL to authorize Whoop, then watch the callback page:\n")
    print(authorize_url())


def _cmd_sync(args: argparse.Namespace) -> None:
    from .sync.runner import sync_all, sync_source

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=args.days - 1)
    source = getattr(args, "source", None)
    if source:
        results = [sync_source(source, start, end, sync_type="manual")]
    else:
        results = sync_all(start, end, sync_type="manual")
    for r in results:
        print(f"  {r.source:12s} {r.status:8s} {r.records_written} records "
              f"{'; '.join(r.errors)}")


def _cmd_backfill(args: argparse.Namespace) -> None:
    from scripts.backfill import run_backfill  # type: ignore

    run_backfill(days=args.days)


def _cmd_infer(args: argparse.Namespace) -> None:
    from .database import get_session
    from .inference.behavioral import run_inference_for_date

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    with get_session() as session:
        day = start
        total = 0
        while day <= end:
            written = run_inference_for_date(session, day)
            total += len(written)
            if written:
                print(f"  {day}: {', '.join(written)}")
            day += timedelta(days=1)
    print(f"Inferred {total} events.")


def _cmd_doctor(args: argparse.Namespace) -> None:
    from .authcheck import ProviderStatus, check_all

    only = getattr(args, "only", None)
    print("HealthOS auth check:\n")
    rows = check_all(only=only)
    for r in rows:
        status = ProviderStatus(**r)
        print(f"  {status.symbol} {status.provider:12s} {status.detail}")
    print("\n  ✓ connected   ✗ configured but failing   ○ not set up yet")


def _cmd_summary(args: argparse.Namespace) -> None:
    from .database import get_session
    from .queries import canonical_value, rolling_baseline

    day = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)
    metrics = ["recovery_score", "hrv_rmssd", "resting_hr", "sleep_duration_minutes", "steps"]
    with get_session() as session:
        print(f"Summary for {day}:")
        for m in metrics:
            val = canonical_value(session, day, m)
            base = rolling_baseline(session, m, day)
            base_str = f"(base {base.mean:.0f}, n={base.n})" if base.mean is not None else ""
            print(f"  {m:24s} {val if val is not None else '—'} {base_str}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="healthos", description="HealthOS CLI")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db").set_defaults(func=_cmd_init_db)
    sub.add_parser("setup").set_defaults(func=_cmd_setup)
    sub.add_parser("whoop-auth").set_defaults(func=_cmd_whoop_auth)

    d = sub.add_parser("doctor")
    d.add_argument(
        "--only",
        choices=["whoop", "garmin", "eight_sleep"],
        default=None,
        help="check a single provider (avoids poking rate-limited ones)",
    )
    d.set_defaults(func=_cmd_doctor)

    s = sub.add_parser("sync")
    s.add_argument("--days", type=int, default=1)
    s.add_argument(
        "--source",
        choices=["whoop", "garmin", "eight_sleep"],
        default=None,
        help="sync a single provider (default: all)",
    )
    s.set_defaults(func=_cmd_sync)

    b = sub.add_parser("backfill")
    b.add_argument("--days", type=int, default=90)
    b.set_defaults(func=_cmd_backfill)

    i = sub.add_parser("infer")
    i.add_argument("--start", required=True)
    i.add_argument("--end", required=True)
    i.set_defaults(func=_cmd_infer)

    su = sub.add_parser("summary")
    su.add_argument("--date", default=None)
    su.set_defaults(func=_cmd_summary)
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
