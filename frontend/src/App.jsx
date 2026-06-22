import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import { useHealthData } from "./hooks/useHealthData.js";
import DailyView from "./views/DailyView.jsx";
import TrendsView from "./views/TrendsView.jsx";
import CorrelationsView from "./views/CorrelationsView.jsx";
import CoverageView from "./views/CoverageView.jsx";
import SignalsView from "./views/SignalsView.jsx";
import WorkoutsView from "./views/WorkoutsView.jsx";

const VIEWS = {
  daily: { label: "Daily", component: DailyView },
  trends: { label: "Trends", component: TrendsView },
  workouts: { label: "Workouts", component: WorkoutsView },
  signals: { label: "Signals", component: SignalsView },
  correlations: { label: "Correlations", component: CorrelationsView },
  coverage: { label: "Coverage", component: CoverageView },
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
// Fires the background sync, polls until done, then reloads to show fresh data.
function RefreshButton() {
  const [state, setState] = useState("idle"); // idle | syncing | done | error
  const poll = useRef(null);
  useEffect(() => () => clearInterval(poll.current), []);

  const start = async () => {
    if (state === "syncing") return;
    setState("syncing");
    const r = await api.triggerSync(7).catch(() => ({ started: false }));
    if (!r.started) {
      // Another sync already running — just poll it to completion.
    }
    poll.current = setInterval(async () => {
      const s = await api.syncStatus().catch(() => null);
      if (s && !s.running) {
        clearInterval(poll.current);
        setState(s.error ? "error" : "done");
        if (!s.error) setTimeout(() => window.location.reload(), 600);
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
  return h in VIEWS ? h : "daily";
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
