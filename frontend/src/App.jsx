import { useState } from "react";
import { api } from "./api.js";
import { useHealthData } from "./hooks/useHealthData.js";
import DailyView from "./views/DailyView.jsx";
import TrendsView from "./views/TrendsView.jsx";
import CorrelationsView from "./views/CorrelationsView.jsx";
import CoverageView from "./views/CoverageView.jsx";

const VIEWS = {
  daily: { label: "Daily", component: DailyView },
  trends: { label: "Trends", component: TrendsView },
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

export default function App() {
  const [view, setView] = useState("daily");
  const Active = VIEWS[view].component;

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
              onClick={() => setView(key)}
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
