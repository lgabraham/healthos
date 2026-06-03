# HealthOS

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

# First-time Whoop auth (CLI prints a consent URL; visit it, approve,
# then copy the tokens from the callback page into .env)
healthos whoop-auth
uvicorn healthos.main:app --reload   # callback lands at /auth/whoop/callback

# Pull data
python -m scripts.backfill --days 90   # historical backfill (rate-limit friendly)
healthos summary                       # sanity-check a day from the CLI

# Frontend
cd frontend && pnpm install && pnpm dev   # http://localhost:5173 (proxies to :8000)
```

The nightly sync runs automatically inside the API process at `SYNC_HOUR` local
time (default 06:00). Trigger an ad-hoc sync any time:

```bash
curl -X POST "localhost:8000/api/admin/sync"                       # yesterday, all sources
curl -X POST "localhost:8000/api/admin/sync?start=2026-05-01&end=2026-05-07&source=whoop"
```

## Canonical sources

When multiple devices report the same metric, all are stored but exactly one is
flagged `is_canonical`. See `healthos/canonical.py` for the full map:

| Metric | Canonical |
|---|---|
| HRV, resting HR, sleep duration & staging, recovery, strain | **whoop** |
| Exercise HR, VO₂ max, training load / TSS, steps, workouts | **garmin** |
| Sleep environment (bed/skin/room temp, toss & turn) | **eight_sleep** |

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

Inference is **suppressed entirely until 14+ days of data exist**; the dashboard
shows a "building baseline" banner during this period. Replay historical
inference without re-syncing via `POST /api/admin/reinfer?start=…&end=…` or
`healthos infer --start … --end …`.

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
`get_workout_history`, `get_events`, `correlate`, `query_raw` (read-only SELECT
guardrails), plus `data_overview`. Trend answers always carry sample size and
flag baselines under 30 days.

Add to Claude Desktop using `claude_desktop_config.example.json` (copy into your
`claude_desktop_config.json`, set `cwd` and `DATABASE_URL`). Then ask things
like *"How did my HRV change the week after heavy training blocks?"*

## Dashboard

Three views — **Daily** (recovery, HRV vs baseline, sleep segments, events, last
workout), **Trends** (30/60/90-day toggle with 7-day rolling averages and event
markers), and **Correlations** (scatter + r + sample size + plain-language read).
Dark `#0a0a0a`, amber `#f59e0b` accent, IBM Plex Mono for values.

Build for production with `pnpm build` (outputs `frontend/dist/`), deploy to
Vercel, or serve the static bundle behind any host. Point it at the API with
`VITE_API_BASE` if the API lives on a different origin.

## Deploy (Railway)

`railway.json` runs `alembic upgrade head` then boots uvicorn. Provision a
Postgres plugin, set the env vars from `.env.example`, and the embedded
scheduler handles nightly syncs — no separate worker needed.

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
- **Secrets** live only in env vars / `.env` (gitignored). Whoop tokens rotate
  on refresh; re-paste them after the first OAuth if you persist them manually.
