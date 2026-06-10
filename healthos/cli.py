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


def _cmd_es_raw(_args: argparse.Namespace) -> None:
    """Map every Eight Sleep device + user and report each one's newest data."""
    from .sync.eight_sleep import EightSleepClient

    def interval_span(intervals: list[dict]) -> str:
        ts = sorted(i.get("ts", "") for i in intervals if i.get("ts"))
        if not ts:
            return "no timestamps"
        return f"{ts[0][:10]} .. {ts[-1][:10]}"

    client = EightSleepClient()
    try:
        token_uid = client.login()
        me = client.me()
        u = me.get("user") or me
        print(f"# logged in as: {u.get('firstName', '?')}  userId={token_uid}")

        user_ids: set[str] = {token_uid}
        for key in ("sharingMetricsTo", "sharingMetricsFrom"):
            for uid in u.get(key) or []:
                user_ids.add(str(uid))

        device_ids = list(u.get("devices") or [])
        cur = u.get("currentDevice") or {}
        if cur.get("id"):
            device_ids.append(cur["id"])

        print("\n# devices")
        for did in dict.fromkeys(device_ids):  # de-dupe, keep order
            try:
                dev = client.device(did)
                d = dev.get("result") or dev
                print(f"  {did}")
                for k in ("deviceId", "ownerId", "leftUserId", "rightUserId", "timezone"):
                    if d.get(k):
                        print(f"      {k}: {d[k]}")
                        if k.endswith("UserId") or k == "ownerId":
                            user_ids.add(str(d[k]))
            except Exception as exc:  # noqa: BLE001
                print(f"  {did}  (detail failed: {exc})")

        print("\n# intervals per user (newest data wins)")
        for uid in user_ids:
            try:
                ivals = client.intervals(uid).get("intervals", [])
                tag = " <- YOU" if uid == token_uid else ""
                print(f"  {uid}{tag}: {len(ivals)} sessions   {interval_span(ivals)}")
            except Exception as exc:  # noqa: BLE001
                print(f"  {uid}: failed ({exc})")
    finally:
        client.close()


def _cmd_whoop_raw(args: argparse.Namespace) -> None:
    """Dump one page of each Whoop v2 endpoint (debugging aid)."""
    import json
    from datetime import datetime, time

    from .config import settings
    from .sync.whoop import WhoopClient

    client = WhoopClient.from_store()
    start = datetime.combine(date.today() - timedelta(days=args.days), time.min, tzinfo=settings.tz)
    end = datetime.combine(date.today(), time.max, tzinfo=settings.tz)
    try:
        for path in ("/v2/recovery", "/v2/activity/sleep", "/v2/activity/workout", "/v2/cycle"):
            print(f"# {path}")
            try:
                page = client.first_page(path, start, end)
                recs = page.get("records", [])
                print(f"  records: {len(recs)}")
                if recs:
                    print(json.dumps(recs[0], indent=2)[:1500])
            except Exception as exc:  # noqa: BLE001
                print(f"  failed: {exc}")
            print()
    finally:
        client.close()


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
        choices=["whoop", "garmin", "eight_sleep", "calendar"],
        default=None,
        help="sync a single source (default: all)",
    )
    s.set_defaults(func=_cmd_sync)

    b = sub.add_parser("backfill")
    b.add_argument("--days", type=int, default=90)
    b.set_defaults(func=_cmd_backfill)

    i = sub.add_parser("infer")
    i.add_argument("--start", required=True)
    i.add_argument("--end", required=True)
    i.set_defaults(func=_cmd_infer)

    er = sub.add_parser("es-raw", help="dump Eight Sleep raw trends JSON")
    er.add_argument("--days", type=int, default=3)
    er.set_defaults(func=_cmd_es_raw)

    wr = sub.add_parser("whoop-raw", help="dump one page of each Whoop v2 endpoint")
    wr.add_argument("--days", type=int, default=7)
    wr.set_defaults(func=_cmd_whoop_raw)

    su = sub.add_parser("summary")
    su.add_argument("--date", default=None)
    su.set_defaults(func=_cmd_summary)
    return p


def main() -> None:
    import logging
    import os

    # Surface INFO-level progress (sync heartbeats, Garmin login) on the console
    # so long-running commands don't look hung. LOG_LEVEL can override.
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
