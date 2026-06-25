"""Live sauna capture: a poll loop over MyHarvia's current device state.

MyHarvia has no history API, so a confirmed sauna session can only be caught
while it's happening. Instead of holding an AppSync websocket open, this polls
``getDeviceState`` (~every 60s) on the always-on host and watches the stove's
``active`` flag: a 1→0 edge means a heating session just ended, which becomes a
confirmed ``sauna`` day-event.

Restart safety: the in-progress session (start time + the last time the stove
was seen on) is persisted to a small JSON state file. If launchd restarts the
process mid-session, ``recover()`` reads it back and either keeps counting (if
the stove is still on) or closes the session out using the last-seen-active
time (if it turned off while we were down).

Run it with ``healthos harvia-monitor`` (see ``deploy/com.healthos.harvia-monitor.plist``
for the launchd service). Resolution is ~one poll interval at each end, which is
well within tolerance for a 20–60 min session rounded to whole minutes.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from ..config import settings
from .harvia import (
    SOURCE,
    HarviaAuthError,
    HarviaClient,
    identify_sauna_device,
    is_active,
    sauna_event,
)
from .persistence import EventRecord

log = logging.getLogger(__name__)


def _write_events(events: list[EventRecord]) -> None:
    """Default sink: persist confirmed events + a sync_log row, like the runner."""
    from ..database import get_session
    from .persistence import SyncResult, upsert_events, write_sync_log

    with get_session() as session:
        n = upsert_events(session, events)
        write_sync_log(session, SyncResult(source=SOURCE, sync_type="live", records_written=n))


class SaunaMonitor:
    """Polls one Harvia stove and records a confirmed event per heating session.

    ``client``, ``now`` (clock) and ``writer`` (event sink) are injectable so the
    transition logic can be exercised without a live login, real time, or a DB —
    mirroring how ``test_harvia`` drives the client with a mock transport.
    """

    def __init__(
        self,
        client: HarviaClient | None = None,
        *,
        state_path: str | Path | None = None,
        poll_seconds: int | None = None,
        now=time.time,
        writer=None,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._state_path = Path(state_path or settings.harvia_state_file)
        self._poll_seconds = poll_seconds or settings.harvia_poll_seconds
        self._now = now
        self._writer = writer or _write_events
        self._device_id: str | None = None
        self._start: float | None = None  # in-progress session start (epoch)
        self._last_active: float | None = None  # last epoch the stove was seen on
        self._load_state()

    # -- client ------------------------------------------------------------
    def _ensure_client(self) -> HarviaClient:
        if self._client is None:
            self._client = HarviaClient()
            self._client.login()
        return self._client

    # -- state file --------------------------------------------------------
    def _load_state(self) -> None:
        try:
            data = json.loads(self._state_path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        self._device_id = data.get("device_id")
        self._start = data.get("session_start")
        self._last_active = data.get("last_active")
        if self._start is not None:
            log.info("Resuming in-progress sauna session from %s", self._state_path)

    def _save_state(self) -> None:
        if self._start is None:
            self._state_path.unlink(missing_ok=True)
            return
        self._state_path.write_text(
            json.dumps(
                {
                    "device_id": self._device_id,
                    "session_start": self._start,
                    "last_active": self._last_active,
                }
            )
        )

    # -- lifecycle ---------------------------------------------------------
    def identify(self) -> str:
        device_id = identify_sauna_device(self._ensure_client())
        if not device_id:
            raise HarviaAuthError("No Harvia sauna device found (none exposed an 'active' state).")
        self._device_id = device_id
        log.info("Monitoring Harvia sauna device %s", device_id)
        return device_id

    def recover(self) -> EventRecord | None:
        """Close out a session that ended while the process was down.

        Only does anything when the state file held an in-progress session: if the
        stove is now off it's recorded (end = last time we saw it on); if it's
        still on we keep counting from the saved start.
        """
        if self._start is None:
            return None
        state = self._ensure_client().device_state(self._device_id)
        if is_active(state):
            return None  # still heating — the loop will close it normally
        return self._close_session(end=self._last_active or self._start)

    def poll_once(self) -> EventRecord | None:
        """One poll: read state, track the on/off edge, emit an event on 1→0."""
        state = self._ensure_client().device_state(self._device_id)
        active = is_active(state)
        now = self._now()
        if active:
            if self._start is None:
                self._start = now
                log.info("Sauna session started")
            self._last_active = now
            self._save_state()
            return None
        if self._start is not None:  # 1 -> 0: session ended this poll
            return self._close_session(end=now)
        return None

    def _close_session(self, end: float) -> EventRecord | None:
        start = self._start or end
        self._start = None
        self._last_active = None
        self._save_state()
        event = sauna_event(start, end)
        if event is None:
            log.info("Sauna run %.0fs below minimum; not recorded", end - start)
            return None
        self._writer([event])
        log.info("Recorded sauna event: %s min on %s", event.value, event.date)
        return event

    def run(self) -> None:
        """Blocking poll loop. Individual poll failures are logged, not fatal —
        a transient network/auth blip shouldn't kill an always-on monitor."""
        self.identify()
        try:
            self.recover()
        except Exception:  # noqa: BLE001 - recovery is best-effort
            log.exception("Sauna session recovery failed")
        log.info("Harvia monitor polling every %ds", self._poll_seconds)
        try:
            while True:
                try:
                    self.poll_once()
                except Exception:  # noqa: BLE001 - keep the monitor alive
                    log.exception("Harvia poll failed")
                time.sleep(self._poll_seconds)
        finally:
            if self._owns_client and self._client is not None:
                self._client.close()
