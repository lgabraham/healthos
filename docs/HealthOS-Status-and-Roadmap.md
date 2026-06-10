---
tags: [healthos, project, health-data]
status: active
updated: 2026-06-10
repo: github.com/lgabraham/sandbox (branch claude/healthos-health-aggregator-ClbmY)
---

# HealthOS — Status & Roadmap

A personal health-data aggregator: pulls **Whoop, Garmin, Eight Sleep, Apple Health, and Google Calendar** into one Postgres database on the always-on M1 (`node-m1`), serves a dark mission-control dashboard at `http://node-m1:8000` (over Tailscale), runs nightly sync + behavioral inference, and exposes an **MCP server** so Claude can answer questions about the data.

## What it does today

### Data sources
| Source | Provides | Status |
|---|---|---|
| **Whoop** | recovery, HRV, resting HR, sleep stages, strain, SpO₂, respiratory rate, workouts | ✅ live (data through ~May 28 until strap re-syncs) |
| **Eight Sleep** | bed/room temp, toss & turn, HRV + resting HR from the pod | ✅ live (on the active account) |
| **Garmin** | Body Battery, stress, VO₂ max, steps, training load | ✅ **connected** (session cached; run a 90-day sync) |
| **Apple Health** | daily steps via iOS Shortcut → webhook | ✅ live; **canonical for steps** |
| **Google Calendar** | events auto-classified (alcohol/travel/work/exercise/health) | ✅ live (secret .ics; titles never leave the M1) |

### How it thinks
- **Canonical source per metric** (Whoop=HRV/sleep/recovery; Garmin=training; Eight Sleep=environment; Apple=steps); all sources stored; **labeled fallbacks** fill gaps ("via eight_sleep (fallback)").
- **Estimated recovery** from HRV+RHR vs baseline when Whoop has no score (clearly labeled).
- **Reading rule:** a day's HRV/RHR/sleep = the night that *ended* that morning → last evening's events explain this morning's numbers; effects appear the **next day**.
- **Inference** (needs 14+ days data): alcohol_detected (evening-calendar corroborated), sick, late_workout, sauna, high_stress_day, calendar_heavy_day. Baselines = rolling 30d, sick days excluded.

### Dashboard tabs
1. **Daily** — recovery (real/estimated), HRV/RHR with fallback labels, sleep bars, **"Why today" attribution waterfall** + plain-language headline, calendar context (type chips, prev-day labeled), steps, last workout, date-nav arrows.
2. **Trends** — 30/60/90d lines, 7d rolling avg, event dots, all-source data, **aligned date axes**.
3. **Signals** — HRV + RHR with calendar events as **type-colored dots** (titles hover-only).
4. **Correlations** — scatter cards with Pearson r + n + plain reading.
5. **Coverage** — metric × day heatmap of *which source* filled each cell.

### Infrastructure
FastAPI + Postgres 16 + Alembic on the M1; React/Recharts frontend; nightly sync at 06:00 (in-process scheduler); `healthos` CLI (setup / doctor / sync / infer / es-raw / whoop-raw); MCP server with calendar-title redaction; ~50 tests, CI on GitHub Actions; Dockerfile + Railway config exist as deploy alternatives.

## Known gaps
- Whoop strap not synced since ~May 28 → wear it, open app, `healthos sync --source whoop`.
- Whoop vs Eight Sleep HRV are different instruments — fallback labeled, not yet offset-calibrated.
- Server runs in a foreground terminal (dies on close) → needs launchd service.
- Calendar keyword matching is substring-based ("Coffee Chat" → ✈️) → needs whole-word.
- Rotate credentials exposed during chat setup (Garmin/Eight Sleep passwords, Whoop secret, .ics URL).

## Roadmap (ranked)
**Viz (per Fable 5 review):**
- [x] Recovery Attribution Waterfall ("Why today")
- [ ] Source Concordance Strip — Whoop-vs-pod HRV offset (makes fallbacks trustworthy)
- [ ] Event Response Curves — median metric trajectory −3..+3 days around each event type ("what does alcohol cost me?")
- [ ] Strain–Recovery Ledger — acute:chronic load zones + tomorrow projection from calendar
- [ ] Lagged Correlation Matrix — effects at lag 0/+1/+2
- [ ] Weekday Fingerprint — "your week has a shape"
- [ ] Night Anatomy — hypnogram + bed-temp overlay (needs intra-night persistence)
- [ ] Attention queue — 1–3 advisor lines atop Daily

**Data & ops:**
- [ ] 90-day Garmin backfill, then re-run inference
- [ ] launchd service for true always-on
- [ ] Nightly Apple-steps automation (~11:30pm)
- [ ] Harvia sauna listener (confirmed sauna events via reverse-engineered MyHarvia API)
- [ ] More Apple Health pushes (weight, mindful minutes, active energy)
- [ ] Weather/daylight/pressure as passive context
- [ ] Whole-word calendar matching; PR/merge to main

## Ops cheatsheet (M1)
```bash
cd ~/sandbox/healthos && git pull
cd frontend && node_modules/.bin/vite build && cd ..
lsof -ti tcp:8000 -sTCP:LISTEN | xargs kill -9 2>/dev/null
uvicorn healthos.main:app --host 0.0.0.0 --port 8000
# healthos doctor [--only X] · sync --days N --source X · infer --start --end
```
