import { useState } from "react";
import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";
import TrendChart from "../components/TrendChart.jsx";

const RANGES = [30, 60, 90];

const CHARTS = [
  { metric: "hrv_rmssd", title: "HRV (rmssd) · 7-day rolling", color: "#f59e0b", unit: "ms", goodUp: true },
  { metric: "resting_hr", title: "Resting HR · 7-day rolling", color: "#fb7185", unit: "bpm", goodUp: false },
  {
    metric: "sleep_duration_minutes",
    title: "Sleep duration",
    color: "#38bdf8",
    unit: "min",
    goodUp: true,
    yFormat: (v) => `${Math.floor(v / 60)}h${String(Math.round(v % 60)).padStart(2, "0")}`,
  },
];

// 4-week change = mean of the last 14 days vs the 14 days before that. The
// series is padded one-per-day, so slicing by index = slicing by calendar day.
function fourWeekChange(series) {
  if (!series || series.length < 16) return null;
  const recent = series.slice(-14).map((d) => d.value).filter((v) => v != null);
  const prior = series.slice(-28, -14).map((d) => d.value).filter((v) => v != null);
  if (recent.length < 3 || prior.length < 3) return null;
  const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;
  const r = mean(recent);
  const p = mean(prior);
  return { delta: r - p, pct: p ? ((r - p) / p) * 100 : null };
}

function DeltaBadge({ change, unit, goodUp }) {
  if (!change) return null;
  const { delta, pct } = change;
  const flat = Math.abs(pct ?? 0) < 1.5;
  const improving = delta >= 0 ? goodUp : !goodUp;
  const color = flat ? "var(--muted)" : improving ? "var(--good)" : "var(--bad)";
  const arrow = flat ? "→" : delta > 0 ? "▲" : "▼";
  const d = unit === "min" ? `${Math.round(delta)}m` : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}${unit}`;
  const pctStr = pct == null ? "" : ` (${pct >= 0 ? "+" : ""}${pct.toFixed(0)}%)`;
  return (
    <span className="mono" style={{ color, fontSize: "0.72rem", whiteSpace: "nowrap" }} title="mean of last 14d vs prior 14d">
      {arrow} {unit === "min" && delta >= 0 ? "+" : ""}{d}{pctStr} · 4wk
    </span>
  );
}

function Chart({ metric, title, color, days, unit, goodUp, yFormat }) {
  const { data, loading, error } = useHealthData(() => api.trend(metric, days, 7), [metric, days]);
  const change = data ? fourWeekChange(data.series) : null;
  return (
    <div className="panel">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: "0.5rem" }}>
        <div className="label" style={{ marginBottom: 0 }}>{title}</div>
        <DeltaBadge change={change} unit={unit} goodUp={goodUp} />
      </div>
      {loading && <div className="muted mono">loading…</div>}
      {error && <div className="error">error: {error}</div>}
      {data && (
        <>
          <TrendChart series={data.series} events={data.events} color={color} yFormat={yFormat} />
          <div className="muted mono" style={{ fontSize: "0.66rem", marginTop: "0.3rem" }}>
            thin gray = daily · solid = 7d avg · dashed = ~4-week baseline (long-term trend) · band
            = usual range · dots = events
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
