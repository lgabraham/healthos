import { useState } from "react";
import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";
import TrendChart from "../components/TrendChart.jsx";

const RANGES = [30, 60, 90];

const CHARTS = [
  { metric: "hrv_rmssd", title: "HRV (rmssd) · 7-day rolling", color: "#f59e0b" },
  {
    metric: "sleep_duration_minutes",
    title: "Sleep duration",
    color: "#38bdf8",
    yFormat: (v) => `${Math.floor(v / 60)}h${String(Math.round(v % 60)).padStart(2, "0")}`,
  },
  { metric: "strain_score", title: "Training strain", color: "#a855f7" },
];

function Chart({ metric, title, color, days, yFormat }) {
  const { data, loading, error } = useHealthData(() => api.trend(metric, days, 7), [metric, days]);
  return (
    <div className="panel">
      <div className="label">{title}</div>
      {loading && <div className="muted mono">loading…</div>}
      {error && <div className="error">error: {error}</div>}
      {data && (
        <>
          <TrendChart series={data.series} events={data.events} color={color} yFormat={yFormat} />
          <div className="muted mono" style={{ fontSize: "0.66rem", marginTop: "0.3rem" }}>
            thin gray = daily · colored = 7d avg (breaks at gaps) · dots = detected events · drag
            the strip to scroll
          </div>
        </>
      )}
    </div>
  );
}

export default function TrendsView() {
  const [days, setDays] = useState(60);
  return (
    <>
      <div style={{ marginBottom: "1rem" }}>
        <div className="toggle">
          {RANGES.map((r) => (
            <button key={r} className={days === r ? "active" : ""} onClick={() => setDays(r)}>
              {r}d
            </button>
          ))}
        </div>
      </div>
      <div className="grid" style={{ gap: "0.85rem" }}>
        {CHARTS.map((c) => (
          <Chart key={c.metric} {...c} days={days} />
        ))}
      </div>
    </>
  );
}
