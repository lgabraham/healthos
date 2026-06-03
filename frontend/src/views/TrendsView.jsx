import { useState } from "react";
import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";
import TrendChart from "../components/TrendChart.jsx";

const RANGES = [30, 60, 90];

const CHARTS = [
  { metric: "hrv_rmssd", title: "HRV (rmssd) · 7-day rolling", color: "#f59e0b" },
  { metric: "sleep_duration_minutes", title: "Sleep duration", color: "#38bdf8" },
  { metric: "strain_score", title: "Training strain", color: "#a855f7" },
];

function Chart({ metric, title, color, days }) {
  const { data, loading, error } = useHealthData(() => api.trend(metric, days, 7), [metric, days]);
  return (
    <div className="panel">
      <div className="label">{title}</div>
      {loading && <div className="muted mono">loading…</div>}
      {error && <div className="error">error: {error}</div>}
      {data && <TrendChart series={data.series} events={data.events} color={color} />}
    </div>
  );
}

export default function TrendsView() {
  const [days, setDays] = useState(30);
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
