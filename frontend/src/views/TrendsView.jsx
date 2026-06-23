import { useState } from "react";
import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";
import TrendChart from "../components/TrendChart.jsx";

// 1y (365) also clamps to your earliest data on the backend, so it doubles as
// "all history" until there's more than a year stored.
const RANGES = [30, 60, 90, 365];
const rangeLabel = (d) => (d >= 365 ? "1y" : `${d}d`);

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

// Change across the *visible* range: mean of the first half vs the second half
// of the series (so the badge matches the trend you're looking at). Padded
// one-per-day, so the two halves are equal calendar spans.
function rangeChange(series) {
  if (!series || series.length < 8) return null;
  const mid = Math.floor(series.length / 2);
  const first = series.slice(0, mid).map((d) => d.value).filter((v) => v != null);
  const second = series.slice(mid).map((d) => d.value).filter((v) => v != null);
  if (first.length < 3 || second.length < 3) return null;
  const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;
  const f = mean(first);
  const s = mean(second);
  return { delta: s - f, pct: f ? ((s - f) / f) * 100 : null };
}

function DeltaBadge({ change, unit, goodUp, days }) {
  if (!change) return null;
  const { delta, pct } = change;
  const flat = Math.abs(pct ?? 0) < 1.5;
  const improving = delta >= 0 ? goodUp : !goodUp;
  const color = flat ? "var(--muted)" : improving ? "var(--good)" : "var(--bad)";
  const arrow = flat ? "→" : delta > 0 ? "▲" : "▼";
  const d = unit === "min" ? `${Math.round(delta)}m` : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}${unit}`;
  const pctStr = pct == null ? "" : ` (${pct >= 0 ? "+" : ""}${pct.toFixed(0)}%)`;
  return (
    <span
      className="mono"
      style={{ color, fontSize: "0.72rem", whiteSpace: "nowrap" }}
      title={`change over the ${rangeLabel(days)} window (first half vs second half)`}
    >
      {arrow} {unit === "min" && delta >= 0 ? "+" : ""}{d}{pctStr} · {rangeLabel(days)}
    </span>
  );
}

function Chart({ metric, title, color, days, unit, goodUp, yFormat }) {
  const { data, loading, error } = useHealthData(() => api.trend(metric, days, 7), [metric, days]);
  const change = data ? rangeChange(data.series) : null;
  return (
    <div className="panel">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: "0.5rem" }}>
        <div className="label" style={{ marginBottom: 0 }}>{title}</div>
        <DeltaBadge change={change} unit={unit} goodUp={goodUp} days={days} />
      </div>
      {loading && <div className="muted mono">loading…</div>}
      {error && <div className="error">error: {error}</div>}
      {data && (
        <>
          <TrendChart series={data.series} color={color} yFormat={yFormat} />
          <div className="muted mono" style={{ fontSize: "0.66rem", marginTop: "0.3rem" }}>
            thin gray = daily · solid = 7d avg · dashed = ~4-week baseline (long-term trend) · band
            = usual range
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
              {rangeLabel(r)}
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
