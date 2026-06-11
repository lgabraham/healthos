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
  rem_sleep_minutes: "REM sleep",
  deep_sleep_minutes: "Deep sleep",
  light_sleep_minutes: "Light sleep",
  awake_minutes: "Awake",
  sleep_efficiency: "Sleep efficiency",
  respiratory_rate: "Resp. rate",
  spo2: "SpO₂",
  steps: "Steps",
  vo2_max: "VO₂ max",
  training_load: "Training load",
  tss: "TSS",
  body_battery: "Body Battery",
  stress_avg: "Stress",
  exercise_hr: "Exercise HR",
  bed_temp: "Bed temp",
  skin_temp: "Skin temp",
  room_temp: "Room temp",
  toss_turn_count: "Toss & turn",
};
function mlabel(m) {
  return LABELS[m] || m.replace(/_/g, " ");
}

// Plain-English statement of how the winning value is chosen for a metric.
function resolutionRule({ resolution: r }) {
  if (!r) return null;
  const canon = r.canonical || "(no canonical owner)";
  const chain = r.fallback_order.length ? ` → else ${r.fallback_order.join(" → ")}` : "";
  const zero = r.zero_is_missing ? " · 0 = missing" : "";
  const win = r.current_winner
    ? ` · now winning: ${r.current_winner}${r.current_winner_is_fallback ? " (fallback)" : ""} as of ${r.as_of}`
    : "";
  return `wins: ${canon}${chain}${zero}${win}`;
}

// Device-by-metric matrix: every metric and which gadgets feed it. The
// canonical source is starred; fallbacks show their day-count so you can see,
// e.g., HRV = Whoop 40d (canonical) + Eight Sleep 18d + Garmin 30d.
function DeviceMatrix() {
  const { data, loading, error } = useHealthData(() => api.metricSources(90), []);
  if (loading) return <div className="muted mono">loading…</div>;
  if (error) return <div className="error">error: {error}</div>;
  if (!data?.metrics?.length) return null;
  return (
    <div className="panel" style={{ marginBottom: "0.85rem", overflowX: "auto" }}>
      <div className="label">Devices by metric · last {data.window_days} days · ★ canonical</div>
      <table className="devmatrix">
        <tbody>
          {data.metrics.map((row) => (
            <tr key={row.metric}>
              <td className="dm-metric">{mlabel(row.metric)}</td>
              <td className="dm-total">{row.total_days}d</td>
              <td>
                <div className="dm-sources">
                  {row.sources.map((s) => (
                    <span
                      key={s.source}
                      className="dm-chip"
                      title={`${s.source}: ${s.days} days · last ${s.last_date}${
                        s.days_behind > 2 ? ` (${s.days_behind}d behind)` : ""
                      }`}
                      style={{
                        borderColor: color(s.source),
                        opacity: s.days_behind > 7 ? 0.5 : 1,
                      }}
                    >
                      <i style={{ background: color(s.source) }} />
                      {s.canonical ? "★ " : ""}
                      {s.source} {s.days}d
                    </span>
                  ))}
                </div>
                <div className="dm-rule">{resolutionRule(row)}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

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
      <DeviceMatrix />
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
