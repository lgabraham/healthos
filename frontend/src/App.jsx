import { useState } from "react";
import { api } from "./api.js";
import { useHealthData } from "./hooks/useHealthData.js";
import DailyView from "./views/DailyView.jsx";
import TrendsView from "./views/TrendsView.jsx";
import CorrelationsView from "./views/CorrelationsView.jsx";
import CoverageView from "./views/CoverageView.jsx";
import SignalsView from "./views/SignalsView.jsx";

const VIEWS = {
  daily: { label: "Daily", component: DailyView },
  trends: { label: "Trends", component: TrendsView },
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
        <StatusLine />
      </div>
      <Active />
    </div>
  );
}
