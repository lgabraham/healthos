import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import { useHealthData, triggerGlobalRefresh } from "./hooks/useHealthData.js";
import DailyView from "./views/DailyView.jsx";
import TrendsView from "./views/TrendsView.jsx";
import WorkoutsView from "./views/WorkoutsView.jsx";
import StreaksView from "./views/StreaksView.jsx";
import JournalView from "./views/JournalView.jsx";

const VIEWS = {
  pulse: { label: "Pulse", component: DailyView },
  streak: { label: "Streak", component: StreaksView },
  trends: { label: "Trends", component: TrendsView },
  workouts: { label: "Workouts", component: WorkoutsView },
  journal: { label: "Journal", component: JournalView },
};

function StatusLine() {
  const { data } = useHealthData(() => api.status(), []);
  if (!data) return <span className="statusline">connecting…</span>;
  const last = data.last_sync;
  return (
    <span className="statusline">
      {data.data_days}d data · tz {data.timezone}
      {last ? ` · last sync ${last.source}/${last.status}` : " · no sync yet"}
    </span>
  );
}

// Re-pull recent days (replace mode) so upstream edits/deletions — e.g. an
// Eight Sleep session you removed because a kid was in the bed — take effect.
// Fires the background sync, polls until done, then refreshes the data in place
// (no page reload, so unsaved Journal/Workout form text survives).
const MAX_POLLS = 80; // ~2 min at 1.5s — stop polling if sync-status never settles

function RefreshButton() {
  const [state, setState] = useState("idle"); // idle | syncing | done | error
  const poll = useRef(null);
  useEffect(() => () => clearInterval(poll.current), []);

  const start = async () => {
    if (state === "syncing") return;
    setState("syncing");
    await api.triggerSync(7).catch(() => ({ started: false }));
    let polls = 0;
    poll.current = setInterval(async () => {
      const s = await api.syncStatus().catch(() => null);
      if ((s && !s.running) || ++polls >= MAX_POLLS) {
        clearInterval(poll.current);
        const errored = !s || s.error || polls >= MAX_POLLS;
        setState(errored ? "error" : "done");
        if (!errored) triggerGlobalRefresh();
      }
    }, 1500);
  };

  const label = { idle: "↻ refresh", syncing: "syncing…", done: "✓ updated", error: "✗ failed" }[
    state
  ];
  return (
    <button
      className="refresh"
      onClick={start}
      disabled={state === "syncing"}
      title="Re-pull the last 7 days from all devices (reflects deleted/edited sessions)"
    >
      {label}
    </button>
  );
}

function viewFromHash() {
  const h = window.location.hash.replace("#", "");
  if (h === "sleep") return "streak"; // sleep was folded into the streak tab
  if (h === "daily") return "pulse"; // Daily was renamed to Pulse
  return h in VIEWS ? h : "pulse";
}

export default function App() {
  const [view, setView] = useState(viewFromHash);
  const Active = VIEWS[view].component;
  const switchView = (key) => {
    window.location.hash = key;
    setView(key);
  };

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">
          HEALTH<span className="dot">·</span>OS
        </div>
        <nav className="nav">
          {Object.entries(VIEWS).map(([key, { label }]) => (
            <button
              key={key}
              className={view === key ? "active" : ""}
              onClick={() => switchView(key)}
            >
              {label}
            </button>
          ))}
        </nav>
        <div style={{ display: "flex", alignItems: "center", gap: "0.7rem" }}>
          <StatusLine />
          <RefreshButton />
        </div>
      </div>
      <Active />
    </div>
  );
}
