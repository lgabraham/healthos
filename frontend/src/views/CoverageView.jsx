import { useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";

// Which source filled each (metric, day) cell — gaps and provenance at a glance.
const SOURCE_COLOR = {
  whoop: "#f59e0b",
  garmin: "#4ade80",
  eight_sleep: "#38bdf8",
  apple_health: "#a855f7",
  ios_shortcut: "#a855f7",
  estimated: "#6b7280",
};

const LABELS = {
  recovery_score: "Recovery",
  hrv_rmssd: "HRV",
  resting_hr: "Resting HR",
  strain_score: "Strain",
  sleep_duration_minutes: "Sleep",
  respiratory_rate: "Resp. rate",
  spo2: "SpO₂",
  steps: "Steps",
};

function color(source) {
  return source ? SOURCE_COLOR[source] || "#777" : "#161616";
}

const AXIS = { stroke: "#3f3f46", fontSize: 11, fontFamily: "IBM Plex Mono" };
const CONC_METRICS = [
  { key: "hrv_rmssd", label: "HRV", unit: "ms" },
  { key: "resting_hr", label: "Resting HR", unit: "bpm" },
  { key: "sleep_duration_minutes", label: "Sleep", unit: "min" },
];

// Whoop vs Eight Sleep on the SAME nights: quantifies the instrument offset
// (so fallback numbers can be read honestly) and exposes one-off divergent
// nights — e.g. the pod measuring a different occupant of the bed.
function ConcordancePanel() {
  const [metric, setMetric] = useState("hrv_rmssd");
  const { data, loading, error } = useHealthData(() => api.concordance(metric, 60), [metric]);
  const meta = CONC_METRICS.find((m) => m.key === metric);

  return (
    <div className="panel" style={{ marginTop: "0.85rem" }}>
      <div className="label">Source concordance · whoop vs eight_sleep · 60d</div>
      <div style={{ display: "flex", gap: "0.6rem", alignItems: "center", margin: "0.4rem 0" }}>
        <div className="toggle">
          {CONC_METRICS.map((m) => (
            <button
              key={m.key}
              className={metric === m.key ? "active" : ""}
              onClick={() => setMetric(m.key)}
            >
              {m.label}
            </button>
          ))}
        </div>
        {data && data.n_overlap > 0 && (
          <span className="metric-sub">
            {data.n_overlap} shared nights · pod reads{" "}
            <span style={{ color: "var(--accent)" }}>
              {data.median_offset > 0 ? "+" : ""}
              {data.median_offset}
              {meta.unit}
            </span>{" "}
            vs strap (median) {data.r != null ? `· r=${data.r}` : ""}
          </span>
        )}
        {data && data.n_overlap === 0 && (
          <span className="metric-sub">no shared nights in window — wear the strap in bed once to calibrate</span>
        )}
      </div>
      {loading && <div className="muted mono">loading…</div>}
      {error && <div className="error">error: {error}</div>}
      {data && data.series?.length > 0 && (
        <>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={data.series} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
              <CartesianGrid stroke="#1f1f1f" vertical={false} />
              <XAxis dataKey="date" tick={AXIS} minTickGap={28} tickLine={false} axisLine={AXIS} />
              <YAxis tick={AXIS} width={42} tickLine={false} axisLine={AXIS} domain={["auto", "auto"]} />
              <Tooltip
                contentStyle={{
                  background: "#181818",
                  border: "1px solid #262626",
                  fontFamily: "IBM Plex Mono",
                  fontSize: 12,
                }}
                formatter={(v, name) => [`${Number(v).toFixed(1)} ${meta.unit}`, name]}
              />
              <Line
                type="linear"
                dataKey="whoop"
                name="whoop"
                stroke="#f59e0b"
                strokeWidth={2}
                dot={{ r: 2 }}
                isAnimationActive={false}
              />
              <Line
                type="linear"
                dataKey="eight_sleep"
                name="eight_sleep"
                stroke="#38bdf8"
                strokeWidth={2}
                dot={{ r: 2 }}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
          <div className="metric-sub">
            nights where the blue line jumps away from amber = the pod measured something else
            (sensor moved, partner in bed) — treat that night's fallback with suspicion
          </div>
        </>
      )}
    </div>
  );
}

export default function CoverageView() {
  const { data, loading, error } = useHealthData(() => api.coverage(60), []);
  if (loading) return <div className="muted mono">loading…</div>;
  if (error) return <div className="error">error: {error}</div>;

  const { metrics, dates, grid } = data;

  return (
    <>
      <div className="statusline" style={{ marginBottom: "0.8rem" }}>
        data coverage · last {dates.length} days · who filled each cell
      </div>
      <div className="panel" style={{ overflowX: "auto" }}>
        <div className="cov-row" aria-hidden="true">
          <span className="cov-label" />
          <div className="cov-cells">
            {dates.map((date) => (
              <span key={date} className="cov-cell cov-tick">
                {date.endsWith("-01")
                  ? new Date(`${date}T00:00:00`).toLocaleString("en", { month: "short" })
                  : ""}
              </span>
            ))}
          </div>
        </div>
        {metrics.map((metric) => (
          <div className="cov-row" key={metric}>
            <span className="cov-label">{LABELS[metric] || metric}</span>
            <div className="cov-cells">
              {dates.map((date) => (
                <span
                  key={date}
                  className="cov-cell"
                  style={{ background: color(grid[date][metric]) }}
                  title={`${date} · ${grid[date][metric] || "no data"}`}
                />
              ))}
            </div>
          </div>
        ))}
        <div className="legend" style={{ marginTop: "0.8rem" }}>
          {Object.entries(SOURCE_COLOR).map(([src, c]) =>
            src === "ios_shortcut" ? null : (
              <span key={src}>
                <i style={{ background: c }} />
                {src}
              </span>
            )
          )}
          <span>
            <i style={{ background: "#161616" }} />
            missing
          </span>
        </div>
      </div>
      <ConcordancePanel />
    </>
  );
}
