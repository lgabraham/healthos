---
tags: [healthos, ops, deploy]
---

# Always-on + a public URL (free, all on the M1)

Two independent pieces. Do #1 for "survives reboots and crashes"; add #2 for a
public HTTPS URL you can open from anywhere without Tailscale on the client.

Everything here is free: launchd ships with macOS, Tailscale Funnel is included
on the free plan.

---

## 0. Prerequisite — keep Postgres always-on too

The server is useless if its database isn't running. If Postgres came from
Homebrew, make it a boot service (once):

```bash
brew services start postgresql@16   # or whatever version `brew list` shows
```

`brew services list` should show it `started`.

---

## 1. Run the server under launchd (auto-start + auto-restart)

This replaces the manual `nohup uvicorn …` dance. launchd starts it at login
and restarts it if it ever dies.

```bash
# Logs directory the plist points at
mkdir -p ~/sandbox/healthos/logs

# Install the service (copy, don't symlink — launchd wants a real file)
cp ~/sandbox/healthos/deploy/com.healthos.server.plist ~/Library/LaunchAgents/

# Load + start it
launchctl load -w ~/Library/LaunchAgents/com.healthos.server.plist
```

Verify:

```bash
launchctl list | grep healthos          # shows a PID when running
curl -s localhost:8000/api/status | head -c 120
```

**Auto-start across reboots:** a LaunchAgent runs once the `node` user logs in.
On a headless always-on Mac, enable auto-login (System Settings → Users &
Groups → Automatically log in as `node`) so a reboot brings the server back
with no keyboard. (For login-independent boot, use a LaunchDaemon in
`/Library/LaunchDaemons` instead — needs sudo; ask and I'll provide that
variant.)

### Day-to-day

```bash
# After a git pull + frontend rebuild, restart the service:
launchctl kickstart -k gui/$(id -u)/com.healthos.server

# Tail logs
tail -f ~/sandbox/healthos/logs/server.log

# Stop / uninstall
launchctl unload ~/Library/LaunchAgents/com.healthos.server.plist
```

Deploying an update is now just:

```bash
cd ~/sandbox/healthos && git pull && \
  (cd frontend && node_modules/.bin/vite build) && \
  launchctl kickstart -k gui/$(id -u)/com.healthos.server
```

---

## 2. A public URL with Tailscale Funnel (free HTTPS)

Funnel publishes a single port to the public internet over Tailscale's HTTPS,
with an auto-provisioned cert. No Vercel, no port-forwarding, no extra account.

One-time enablement (in the Tailscale admin console → Access Controls): ensure
`funnel` is allowed for this node. Then on the M1:

```bash
# Foreground (test it):
tailscale funnel 8000

# Background (persists):
tailscale funnel --bg 8000

# See the public URL it assigned:
tailscale funnel status
```

You'll get something like `https://node-m1.<your-tailnet>.ts.net` — open that
from any device, Tailscale not required on the client.

To stop publishing:

```bash
tailscale funnel --https=443 off
```

### Tailnet-only alternative (private, no public exposure)

If you'd rather keep it inside your tailnet (current behavior, but with a clean
HTTPS name instead of `node-m1:8000`):

```bash
tailscale serve --bg 8000        # https://node-m1.<tailnet>.ts.net, tailnet-only
```

---

## ⚠️ Before you Funnel: this endpoint has no auth

Today the API trusts anyone who can reach it (it relied on Tailscale being
private). The moment it's on Funnel, **anyone with the URL sees your health
data**. Options, easiest first:

- Keep it tailnet-only (`tailscale serve`, section above) — private, still a
  clean URL.
- Add a bearer-token / basic-auth gate to the FastAPI app before funneling
  (~30 min of work — ask and I'll wire it in).

You said privacy is a nice-to-have, so Funnel-as-is is fine for now; just know
the trade.
