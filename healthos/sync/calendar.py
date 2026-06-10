"""Calendar sync from secret .ics feeds.

Pulls read-only iCal feeds (CALENDAR_ICS_URLS), expands recurring events, and
tags each with behavioral keywords (alcohol/travel) + an evening flag. Titles
are stored for the local dashboard but redacted by the MCP server.
"""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import datetime, timedelta

import httpx

from ..config import settings
from .persistence import CalendarEventRecord

log = logging.getLogger(__name__)

SOURCE = "calendar"

# Keyword -> tag. Matched case-insensitively against title + location. These
# *suggest* context (e.g. an evening "dinner" raises the alcohol prior); they
# never assert on their own.
KEYWORD_TAGS: dict[str, str] = {
    # alcohol / likely-drinking
    "drinks": "alcohol",
    "dinner": "alcohol",
    "happy hour": "alcohol",
    "cocktail": "alcohol",
    "wine": "alcohol",
    "beer": "alcohol",
    "brewery": "alcohol",
    "bar ": "alcohol",
    "pub": "alcohol",
    "party": "alcohol",
    "wedding": "alcohol",
    "birthday": "alcohol",
    "celebration": "alcohol",
    "gala": "alcohol",
    "night out": "alcohol",
    # travel
    "flight": "travel",
    "airport": "travel",
    "layover": "travel",
    "depart": "travel",
    "trip": "travel",
    # work
    "meeting": "work",
    "standup": "work",
    "stand-up": "work",
    "1:1": "work",
    "interview": "work",
    "review": "work",
    "sprint": "work",
    "planning": "work",
    "sync ": "work",
    # exercise
    "gym": "exercise",
    "workout": "exercise",
    "yoga": "exercise",
    "pilates": "exercise",
    "climb": "exercise",
    "training": "exercise",
    # health / appointments
    "doctor": "health",
    "dentist": "health",
    "therapy": "health",
    "appointment": "health",
    "checkup": "health",
}


def tag_keywords(title: str | None, location: str | None) -> list[str]:
    text = f"{title or ''} {location or ''}".lower()
    tags: list[str] = []
    for kw, tag in KEYWORD_TAGS.items():
        if kw in text and tag not in tags:
            tags.append(tag)
    return tags


def _to_local(value) -> tuple[datetime | None, bool]:
    """Return (local datetime or None, is_all_day) for an ics DTSTART value."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=settings.tz)
        return value.astimezone(settings.tz), False
    # A bare date => all-day event.
    return None, True


def normalize_event(event, query_date: _date) -> CalendarEventRecord | None:
    summary = event.get("SUMMARY")
    location = event.get("LOCATION")
    uid = str(event.get("UID") or f"{summary}-{query_date.isoformat()}")

    dtstart = event.get("DTSTART")
    dtend = event.get("DTEND")
    start_local, all_day = _to_local(dtstart.dt) if dtstart else (None, True)
    end_local, _ = _to_local(dtend.dt) if dtend else (None, all_day)

    if all_day or start_local is None:
        day = _date_of(dtstart.dt) if dtstart else query_date
        is_evening = False
    else:
        day = start_local.date()
        is_evening = start_local.hour >= settings.evening_hour

    return CalendarEventRecord(
        date=day,
        uid=uid,
        title=str(summary) if summary is not None else None,
        location=str(location) if location is not None else None,
        start_time=start_local,
        end_time=end_local,
        all_day=all_day,
        is_evening=is_evening,
        keywords=tag_keywords(str(summary) if summary else None,
                              str(location) if location else None),
        source=SOURCE,
    )


def _date_of(value) -> _date:
    return value.date() if isinstance(value, datetime) else value


def fetch_ics(url: str) -> bytes:
    resp = httpx.get(url, timeout=30.0, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def parse_feed(raw: bytes, start: _date, end: _date) -> list[CalendarEventRecord]:
    import icalendar
    import recurring_ical_events

    cal = icalendar.Calendar.from_ical(raw)
    # Expand recurrences across the window (+1 day padding for tz boundaries).
    occurrences = recurring_ical_events.of(cal).between(
        start - timedelta(days=1), end + timedelta(days=1)
    )
    records: list[CalendarEventRecord] = []
    for ev in occurrences:
        rec = normalize_event(ev, query_date=start)
        if rec is not None and start <= rec.date <= end:
            records.append(rec)
    return records


# -- orchestration ----------------------------------------------------------
def pull(start_date: _date, end_date: _date) -> dict:
    """Pull all configured calendars for the inclusive date range."""
    urls = settings.calendar_ics_url_list
    if not urls:
        return {"calendar_events": []}
    records: list[CalendarEventRecord] = []
    for url in urls:
        try:
            records.extend(parse_feed(fetch_ics(url), start_date, end_date))
        except Exception as exc:  # noqa: BLE001 - one bad feed shouldn't kill the rest
            log.warning("Calendar feed failed (%s): %s", url[:40], exc)
    return {"calendar_events": records}
