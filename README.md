# HealthOS

[![HealthOS CI](https://github.com/lgabraham/sandbox/actions/workflows/healthos-ci.yml/badge.svg)](https://github.com/lgabraham/sandbox/actions/workflows/healthos-ci.yml)

A personal health-data aggregator. It pulls **Whoop**, **Garmin**, and **Eight
Sleep** into one Postgres database, serves a dark, data-dense dashboard, runs a
nightly sync + behavioral inference, and exposes an **MCP server** so Claude can
answer natural-language questions about your health trends.

Single-user by design — optimized for clarity and extensibility, not scale.

```
Whoop  ┐
Garmin ├─►  nightly sync ─►  Postgres  ─►  REST API  ─►  React dashboard
Eight  ┘     + inference        │
Sleep                           └─────────►  MCP server  ─►  Claude
```

## Layout

```
healthos/
├── healthos/                 Python package (FastAPI app, sync, inference, MCP)
│   ├── main.py               FastAPI app + scheduler startup
│   ├── config.py             Settings from env vars
│   ├── database.py           SQLAlchemy engine + session factory
│   ├── models.py             ORM models (the 5 core tables)
│   ├── canonical.py          Per-metric canonical-source rules
│   ├── queries.py            Shared reads: baselines, canonical lookups
│   ├── correlate.py          Correlation helpers (metric↔metric, event↔delta)
│   ├── stats.py              Pearson r, rolling average (no numpy)
│   ├── cli.py                `healthos` CLI (init-db, sync, backfill, …)
│   ├── sync/                 whoop / garmin / eight_sleep + runner + scheduler
│   ├── inference/            behavioral.py — alcohol/sick/late-workout/sauna…
│   ├── api/                  metrics, webhooks, auth (Whoop OAuth), admin
│   └── mcp_server/           server.py — tools exposed to Claude
├── frontend/                 React + Vite dashboard (Daily / Trends / Correlations)
├── alembic/                  migrations (0001 = initial schema)
├── scripts/backfill.py       one-time 90-day historical pull
├── tests/                    pytest suite (runs against Postgres)
├── pyproject.toml            uv-managed deps
├── Procfile / railway.json   Railway deploy
└── .env.example
```

## Quick start (local)

Prereqs: Python 3.11+, `uv`, `pnpm`, and a running Postgres.

```bash
cd healthos
cp .env.example .env            # fill in DATABASE_URL + provider creds

# Backend
uv venv && source .venv/bin/activate
uv pip install -e .             # add `.[eightsleep]` to enable Eight Sleep
alembic upgrade head            # create the schema

# First-time Whoop auth — start the API, then open /auth/whoop in a browser,
# approve, and the callback saves tokens to the DB automatically (no copy-paste,
# works from a phone against the deployed URL).
uvicorn healthos.main:app --reload   # then visit http://localhost:8000/auth/whoop

# Pull data
python -m scripts.backfill --days 90   # historical backfill (rate-limit friendly)
healthos summary                       # sanity-check a day from the CLI

# Frontend
cd frontend && pnpm install && pnpm dev   # http://localhost:5173 (proxies to :8000)
```

The nightly sync runs automatically inside the API process at
`SYNC_HOUR:SYNC_MINUTE` local time (default 07:30). Trigger an ad-hoc sync any
time:

```bash
curl -X POST "localhost:8000/api/admin/sync"                       # yesterday, all sources
curl -X POST "localhost:8000/api/admin/sync?start=2026-05-01&end=2026-05-07&source=whoop"
```

## Connecting your accounts (auth)

Put credentials in `.env` (local) or Railway env vars — **never** anywhere
public. Then run `healthos doctor` (or `GET /api/admin/auth-status`) to see what's
connected; it makes a live call per provider and never prints secrets:

```
HealthOS auth check:

  ○ whoop        Set WHOOP_CLIENT_ID/SECRET, then authorize at /auth/whoop.
  ○ garmin       Set GARMIN_EMAIL and GARMIN_PASSWORD.
  ○ eight_sleep  Set EIGHT_SLEEP_EMAIL and EIGHT_SLEEP_PASSWORD.

  ✓ connected   ✗ configured but failing   ○ not set up yet
```

- **Garmin** — set `GARMIN_EMAIL` + `GARMIN_PASSWORD`. That's it (can be done
  from a phone via the Railway dashboard).
- **Eight Sleep** — set `EIGHT_SLEEP_EMAIL` + `EIGHT_SLEEP_PASSWORD`. Support is
  built in (modern OAuth API; the legacy login endpoint old libraries used now
  returns 400).
- **Whoop** — register an app at [developer.whoop.com](https://developer.whoop.com)
  (easiest on desktop), set its redirect URI to `…/auth/whoop/callback`, and put
  `WHOOP_CLIENT_ID` + `WHOOP_CLIENT_SECRET` in env. Then open `/auth/whoop` in any
  browser and approve — tokens are saved to the DB automatically (nothing to
  copy-paste; works from mobile). Re-run `healthos doctor` to confirm a `✓`.

## Securing the dashboard

HealthOS holds your full health history, so gate it behind one shared secret:

```
HEALTHOS_AUTH_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
```

- **Dashboard**: the first visit on a device redirects to a `/login` password
  page; entering the secret sets a 30-day HttpOnly session cookie (log in once).
- **API / webhooks / curl / iOS Shortcut**: send the secret as
  `Authorization: Bearer <token>`, an `X-API-Key` header, or a `?token=` query
  param (handy for the iOS Shortcut URL).

`/health` and the Whoop OAuth callback stay public. If `HEALTHOS_AUTH_TOKEN` is
**unset**, auth is disabled (frictionless local dev) and the app logs a loud
startup warning — so **set it before exposing HealthOS publicly**. The MCP
server talks to the DB directly and isn't exposed over HTTP, so it's unaffected.

## Canonical sources

When multiple devices report the same metric, all are stored but exactly one is
flagged `is_canonical`. See `healthos/canonical.py` for the full map:

| Metric | Canonical |
|---|---|
| HRV, resting HR, sleep duration & staging, sleep environment (bed/skin/room temp, toss & turn) | **eight_sleep** |
| Recovery score, strain, SpO₂, respiratory rate | **whoop** |
| Exercise HR, VO₂ max, training load / TSS, workouts | **garmin** |
| Steps | **apple_health** (Garmin is the fallback) |

Canonical = your *primary* device for each signal (what you actually wear or
sleep on nightly), not the theoretically-best instrument. You sleep on the Eight
Sleep, so it owns the nightly cardiac/sleep signals; Whoop is the labeled
fallback for nights away from the pod. When the canonical device has a gap, the
best-ranked fallback source fills in and is labeled as such.

Baselines use a rolling 30-day window and **exclude days flagged `sick`**.

## Behavioral inference

`healthos/inference/behavioral.py` writes `daily_events` (`confidence='inferred'`):

- **alcohol_detected** — sleep latency > 1.5× baseline **and** RHR > 1.1× 30-day
  avg **and** HRV < 0.85× 30-day avg, with no sick event in the last 3 days.
- **late_workout** — any Garmin workout ending after 19:00 local.
- **sick** — HRV < 0.7× baseline for 2+ consecutive days **and** RHR > 1.15× avg.
- **sauna** — Eight Sleep skin-temp elevated early then a faster-than-average
  drop; requires 30+ nights of baseline and stays low-confidence until confirmed.
- **high_stress_day** — recovery in the red zone (daytime HRV suppression proxy).
- **calendar_heavy_day** — more than `CALENDAR_HEAVY_THRESHOLD` events on a day.

### Calendar context (optional)

Set `CALENDAR_ICS_URLS` to one or more *secret* `.ics` feed URLs (read-only iCal
links). Each sync pulls + expands recurring events and tags them (alcohol /
travel keywords, evening flag). An evening alcohol-tagged event the night before
acts as a corroborating prior — letting `alcohol_detected` fire on 2/3
physiological signals instead of 3/3. Event **titles are stored for the local
dashboard but redacted by the MCP server**, so they never reach Claude.

Inference is **suppressed entirely until 14+ days of data exist**; the dashboard
shows a "building baseline" banner during this period. Replay historical
inference without re-syncing via `POST /api/admin/reinfer?start=…&end=…` or
`healthos infer --start … --end …`.

### Harvia sauna (optional, confirmed events)

If your sauna is a MyHarvia-connected Harvia, set `HARVIA_EMAIL` /
`HARVIA_PASSWORD` to feed **confirmed** `sauna` day-events (`source='harvia'`) —
the device signal that upgrades the low-confidence Eight Sleep thermal
inference. Unset, the source is a clean no-op.

MyHarvia is an AWS Amplify backend (reverse-engineered from the community HA
component [`RubenHarms/ha-harvia-xenio-wifi`](https://github.com/RubenHarms/ha-harvia-xenio-wifi)):

1. **Discovery** (unauthenticated): `GET {HARVIA_ENDPOINT_BASE}/{service}/endpoint`
   for `users`/`device`/`data` returns each service's AppSync GraphQL URL; the
   `users` response also carries the Cognito `userPoolId` / `clientId`.
2. **Auth**: AWS Cognito **SRP** via `pycognito` → an IdToken.
3. **Reads**: `getDeviceTree`, `getDeviceState`, `getLatestData`.

Config (defaults target the app's values; override per account if needed):

- `HARVIA_REGION` (default `eu-west-1`)
- `HARVIA_COGNITO_CLIENT_ID` — auto-discovered from the `users` service; only
  set this to pin it.
- `HARVIA_ENDPOINT_BASE` (default `https://prod.myharvia-cloud.net`)

**Capture-then-poll.** MyHarvia exposes only *current* state + the *latest*
data point — there is **no history query** — so confirmed sessions are recorded
by a persistent monitor (`healthos harvia-monitor`) that polls the stove's
on/off state every `HARVIA_POLL_SECONDS` (default 60) on the always-on M1, not a
nightly pull. It re-authenticates automatically when its Cognito token expires,
so it keeps capturing across long-running sessions. Before its session-detection
is finalized, dump your sauna's live shape:

```bash
healthos harvia-raw   # device tree + each device's state + latest data JSON
```

## Curating events

Inference produces low-confidence guesses; you curate them via `/api/events`:

```bash
# Log an event no device can infer (travel, calendar_heavy_day, ...)
curl -X POST "$HEALTHOS_URL/api/events" \
  -d '{"date":"2026-06-03","event_type":"travel","value":1,"notes":"SFO->JFK"}'

# Confirm an inferred guess (e.g. upgrade a sauna night to 'confirmed')
curl -X POST "$HEALTHOS_URL/api/events/sauna/confirm" -d '{"date":"2026-06-03"}'

# Dismiss a false positive
curl -X DELETE "$HEALTHOS_URL/api/events/alcohol_detected?date=2026-06-03"
```

Confirming sets `confidence='confirmed'` (creating the event if it didn't exist),
manual logging sets `confidence='manual'`, and dismissing removes the row.

## iOS Shortcuts webhook

```bash
curl -X POST "$HEALTHOS_URL/webhooks/ios" \
  -H 'content-type: application/json' \
  -d '{"event_type": "elevated_screen_time", "value": 90, "date": "2026-06-03"}'
```

Stored as `confidence='confirmed'`, `source='ios_shortcut'`.

## MCP server

Run as a separate process against the same DB:

```bash
python -m healthos.mcp_server
```

Tools: `get_daily_summary`, `get_metric_trend`, `get_sleep_history`,
`get_workout_history`, `get_events`, `correlate`, `query_raw`, plus
`data_overview`. Trend answers always carry sample size and flag baselines under
30 days. `query_raw` runs inside a genuinely read-only Postgres transaction with
a statement timeout and a table/column denylist — writes (including
data-modifying CTEs), long-running functions, the OAuth-token table, and the
redacted calendar title/location columns are all rejected.

Add to Claude Desktop using `claude_desktop_config.example.json` (copy into your
`claude_desktop_config.json`, set `cwd` and `DATABASE_URL`). Then ask things
like *"How did my HRV change the week after heavy training blocks?"*

## Dashboard

Tabs — **Pulse** (headliners + full daily breakdown: recovery, HRV vs baseline,
sleep segments, events, last workout), **Streak** (sleep & activity streaks),
**Trends** (30/60/90-day/1y toggle with 7-day rolling averages and event
markers), **Links** (correlations: scatter + r + sample size + plain-language
read), **Workouts**, and **Journal**. Dark `#0a0a0a`, amber `#f59e0b` accent,
IBM Plex Mono for values.

Build for production with `pnpm build` (outputs `frontend/dist/`). Two options:
deploy the bundle to Vercel and point it at the API via `VITE_API_BASE`, **or**
build it and let the FastAPI app serve it from the same origin — if
`frontend/dist/` exists, it's mounted at `/`, so a single Railway service hosts
both the dashboard and the API at one URL (convenient on mobile).

## Deploy (Railway)

The `Dockerfile` builds the dashboard and serves it alongside the API as a
single service; on deploy it runs `alembic upgrade head` then boots uvicorn +
the embedded nightly scheduler — no separate worker or cron. Provision a
Postgres plugin, set the env vars from `.env.example` (**including
`HEALTHOS_AUTH_TOKEN`** — the deploy is public), generate a domain, and
authorize Whoop once at `/auth/whoop`.

Full click-by-click walkthrough: **[DEPLOY.md](DEPLOY.md)**.

## Tests

```bash
uv pip install -e ".[dev]"
pytest          # runs against $DATABASE_URL; tables are truncated per test
ruff check healthos scripts tests
```

## Notes & gotchas

- **Timestamps** are stored UTC; conversion to local time happens only in the
  API responses and MCP output (via `TIMEZONE`).
- **Garmin rate limits** — backfill pulls Garmin in 7-day chunks with pauses;
  there's also a 1s delay between individual Garmin calls.
- **Whoop pagination** — backfill follows `next_token` to completion.
- **Eight Sleep token expiry** — the client rebuilds an authed session per pull
  and skips individual bad nights rather than aborting.
- **Secrets**: Garmin and Eight Sleep are just email/password env vars — set
  them anywhere, including the Railway dashboard on a phone. Whoop is a one-time
  OAuth (register the dev app at developer.whoop.com — easiest on desktop), but
  the consent/callback step persists + refreshes tokens in the DB automatically,
  so there's nothing to copy-paste and it works from mobile too.
