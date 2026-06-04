# Deploying HealthOS to Railway

This gets you an always-on instance: the app runs 24/7, syncs all three sources
every night on its own (no cron to manage), and serves the dashboard + API at a
single URL. ~10 minutes, mostly clicking.

You'll need: a [Railway](https://railway.app) account and this repo on GitHub.

---

## 1. Create the project from this repo

1. Railway → **New Project** → **Deploy from GitHub repo** → pick your fork/repo.
2. When it asks for the root/service, point it at the **`healthos/`** directory
   (that's where the `Dockerfile` lives). Railway detects the Dockerfile and
   builds the single-service image (frontend + API together).

> The build compiles the React dashboard and bakes it into the Python image, so
> there's nothing separate to deploy for the UI.

## 2. Add a Postgres database

1. In the project, **New** → **Database** → **Add PostgreSQL**.
2. Railway creates a `DATABASE_URL` variable. Attach it to the app service:
   open the app service → **Variables** → **Add Reference** → select the
   Postgres `DATABASE_URL`. (Migrations run automatically on every deploy.)

## 3. Set environment variables

On the app service → **Variables**, add:

```
TIMEZONE=America/Los_Angeles      # your timezone
SYNC_HOUR=6                       # local hour for the nightly sync

# Whoop (register an app at developer.whoop.com first)
WHOOP_CLIENT_ID=...
WHOOP_CLIENT_SECRET=...
WHOOP_REDIRECT_URI=https://YOUR-APP.up.railway.app/auth/whoop/callback

# Garmin
GARMIN_EMAIL=...
GARMIN_PASSWORD=...

# Eight Sleep
EIGHT_SLEEP_EMAIL=...
EIGHT_SLEEP_PASSWORD=...
```

Notes:
- You do **not** set `WHOOP_ACCESS_TOKEN` / `REFRESH_TOKEN` — those get created
  and saved automatically when you authorize in step 5.
- `DATABASE_URL` and `PORT` are provided by Railway; don't set them by hand.
- Add credentials right here in the dashboard (works from a phone). They never
  live in the repo or in chat.

## 4. Deploy + get your URL

1. Railway builds and deploys automatically. Watch the **Deploy logs** — you
   should see `alembic upgrade head` run, then `Scheduler started; nightly sync
   at 06:00`.
2. Under **Settings → Networking**, click **Generate Domain**. That's your URL
   (e.g. `https://healthos-production.up.railway.app`). Make sure the Whoop
   `WHOOP_REDIRECT_URI` above matches it, and that the same URI is registered on
   your Whoop developer app.

## 5. Connect Whoop + verify everything

1. Open `https://YOUR-APP.up.railway.app/auth/whoop` in any browser, approve —
   the callback saves your tokens automatically.
2. Check what's connected (no secrets shown):
   `https://YOUR-APP.up.railway.app/api/admin/auth-status`
   Aim for all three `connected: true`. Anything failing comes with a reason.
3. Pull history once (90 days): from the Railway service shell (**⋯ → Shell**),
   run `python -m scripts.backfill --days 90`. After that the nightly job keeps
   it current.
4. Open the root URL — the dashboard. It shows a "building baseline" banner
   until ~14 days of data accrue, then inference kicks in.

---

## Health check & restarts

`railway.json` sets a `/health` healthcheck and restart-on-failure. If a deploy
looks unhealthy, check the deploy logs for the migration/boot output.

## Alternative: split deploy (Vercel + Railway)

Prefer the dashboard on Vercel? Build `frontend/` there and set
`VITE_API_BASE=https://YOUR-API.up.railway.app`, and deploy only the API on
Railway. The single-service Dockerfile above is simpler for one user, though.

## Local smoke test (optional)

```bash
cd healthos
docker build -t healthos .
docker run --rm -p 8000:8000 \
  -e DATABASE_URL="postgresql://user:pass@host:5432/healthos" \
  healthos
# -> dashboard at http://localhost:8000, API under /api, health at /health
```

---

# Self-hosting on an always-on machine

If you have an always-on box (home server / Pi / NAS), you can run the whole
stack there instead of Railway. Two scheduling styles — pick one.

## One-time setup

```bash
git clone <your repo> && cd sandbox/healthos
uv venv && source .venv/bin/activate
uv pip install -e ".[eightsleep]"
cp .env.example .env          # fill in DATABASE_URL + provider creds
alembic upgrade head          # against your Postgres (local or remote)
```

## Option 1 — embedded scheduler (simplest)

Run the app as a long-lived service; its built-in scheduler fires at `SYNC_HOUR`.
Keep `ENABLE_SCHEDULER=true` (the default). Example systemd unit:

```ini
# /etc/systemd/system/healthos.service
[Unit]
Description=HealthOS
After=network-online.target postgresql.service

[Service]
WorkingDirectory=/home/you/sandbox/healthos
EnvironmentFile=/home/you/sandbox/healthos/.env
ExecStart=/home/you/sandbox/healthos/.venv/bin/uvicorn healthos.main:app --host 0.0.0.0 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now healthos
```

## Option 2 — external cron owns the schedule (recommended for a cron box)

Turn the in-process scheduler **off** so the two never double-sync (important for
Garmin's rate limits): set `ENABLE_SCHEDULER=false` in `.env`. Run the web app
the same way (for the dashboard, webhook, OAuth, MCP), then add a cron entry that
runs the sync:

```cron
# crontab -e  — 6:00am local, nightly. Logs to a file you can tail.
0 6 * * *  cd /home/you/sandbox/healthos && .venv/bin/healthos sync >> /var/log/healthos-sync.log 2>&1
```

`healthos sync` pulls all three sources for yesterday and runs inference — the
same work the embedded job does. (Alternatively, hit the running app:
`curl -X POST http://localhost:8000/api/admin/sync`.)

> Note: even self-hosted, the Whoop OAuth callback and the iOS Shortcuts webhook
> need the app reachable at a URL. On a home box, expose it with a tunnel
> (Tailscale, `cloudflared`) or a reverse proxy — you don't need to open ports to
> the public internet.
