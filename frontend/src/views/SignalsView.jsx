import {
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";

// HRV + resting HR over time, with calendar events overlaid as dots colored by
// TYPE. Each event dot sits ON the HRV line for its day, so a "drinks night ->
// HRV dip the next morning" reads directly off the chart. Event titles stay
// local-only (the dashboard runs on the M1, behind Tailscale).
const CAT_COLOR = {
  alcohol: "#f59e0b",
  travel: "#38bdf8",
  work: "#8a8a8a",
  exercise: "#a855f7",
  health: "#ef4444",
  social: "#4ade80",
  other: "#52525b",
};
const AXIS = { stroke: "#3f3f46", fontSize: 11, fontFamily: "IBM Plex Mono" };
const DAYS = 60;

function category(keywords) {
  return (keywords && keywords[0]) || "other";
}

// Event marker: a colored dot bound to a real data point (robust on a category
// axis, unlike ReferenceDot which silently fails to place against string x's).
function EventDot(props) {
  const { cx, cy, payload } = props;
  if (cx == null || cy == null || !payload?.evt) return null;
  return (
    <circle
      cx={cx}
      cy={cy}
      r={5}
      fill={CAT_COLOR[payload.evt] || CAT_COLOR.other}
      stroke="#0a0a0a"
      strokeWidth={1.5}
    />
  );
}

function SignalTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div
      style={{
        background: "#181818",
        border: "1px solid #262626",
        padding: "0.4rem 0.6rem",
        fontFamily: "IBM Plex Mono",
        fontSize: 12,
      }}
    >
      <div style={{ color: "#8a8a8a" }}>{label}</div>
      <div style={{ color: "#f59e0b" }}>HRV: {row.hrv == null ? "—" : row.hrv.toFixed(1)} ms</div>
      <div style={{ color: "#38bdf8" }}>RHR: {row.rhr == null ? "—" : row.rhr.toFixed(1)} bpm</div>
      {row.evt && (
        <div style={{ color: CAT_COLOR[row.evt] || CAT_COLOR.other, marginTop: "0.2rem" }}>
          ● {row.evt}
          {row.evtTitle ? ` · ${row.evtTitle}` : ""}
        </div>
      )}
    </div>
  );
}

export default function SignalsView() {
  const { data: hrv, loading, error } = useHealthData(() => api.trend("hrv_rmssd", DAYS, 7), []);
  const { data: rhr } = useHealthData(() => api.trend("resting_hr", DAYS, 7), []);
  const { data: cal } = useHealthData(() => api.calendar(DAYS), []);

  if (loading) return <div className="muted mono">loading…</div>;
  if (error) return <div className="error">error: {error}</div>;

  const hrvByDate = Object.fromEntries((hrv?.series || []).map((d) => [d.date, d.value]));
  const rhrByDate = Object.fromEntries((rhr?.series || []).map((d) => [d.date, d.value]));
  const events = (cal || []).filter((e) => !e.all_day);

  const hrvValues = Object.values(hrvByDate).filter((v) => v != null);
  const hrvFloor = hrvValues.length ? Math.min(...hrvValues) : 0;

  // One classified event per date (first wins) so a day gets a single marker.
  const evtByDate = {};
  for (const e of events) {
    if (!(e.date in evtByDate)) evtByDate[e.date] = { evt: category(e.keywords), title: e.title };
  }

  // X axis = union of metric dates + event dates, sorted, so every event lands.
  const dates = Array.from(
    new Set([...Object.keys(hrvByDate), ...Object.keys(evtByDate)])
  ).sort();
  const merged = dates.map((date) => {
    const ev = evtByDate[date];
    return {
      date,
      hrv: hrvByDate[date] ?? null,
      rhr: rhrByDate[date] ?? null,
      evt: ev ? ev.evt : null,
      evtTitle: ev ? ev.title : null,
      // Pin the dot to that day's HRV; fall back to the floor if HRV is missing.
      evtY: ev ? (hrvByDate[date] ?? hrvFloor) : null,
    };
  });

  const hasData = merged.some((d) => d.hrv != null || d.rhr != null);
  if (!hasData) {
    return (
      <div className="panel">
        <div className="muted mono">No HRV or resting-HR data in the last {DAYS} days yet.</div>
      </div>
    );
  }

  return (
    <>
      <div className="statusline" style={{ marginBottom: "0.8rem" }}>
        HRV (amber, left) + resting HR (blue, right) · {DAYS}d · calendar events as dots on the HRV
        line, colored by type · titles local-only
      </div>
      <div className="panel">
        <ResponsiveContainer width="100%" height={380}>
          <ComposedChart data={merged} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
            <CartesianGrid stroke="#1f1f1f" vertical={false} />
            <XAxis dataKey="date" tick={AXIS} minTickGap={28} tickLine={false} axisLine={AXIS} />
            <YAxis
              yAxisId="hrv"
              tick={AXIS}
              width={42}
              tickLine={false}
              axisLine={AXIS}
              domain={["auto", "auto"]}
            />
            <YAxis
              yAxisId="rhr"
              orientation="right"
              tick={AXIS}
              width={42}
              tickLine={false}
              axisLine={AXIS}
              domain={["auto", "auto"]}
            />
            <Tooltip content={<SignalTooltip />} />
            <Line
              yAxisId="hrv"
              type="monotone"
              dataKey="hrv"
              name="HRV (ms)"
              stroke="#f59e0b"
              strokeWidth={2}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
            <Line
              yAxisId="rhr"
              type="monotone"
              dataKey="rhr"
              name="RHR (bpm)"
              stroke="#38bdf8"
              strokeWidth={1.5}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
            <Scatter
              yAxisId="hrv"
              dataKey="evtY"
              shape={<EventDot />}
              isAnimationActive={false}
              legendType="none"
            />
          </ComposedChart>
        </ResponsiveContainer>
        <div className="legend" style={{ marginTop: "0.6rem" }}>
          {Object.entries(CAT_COLOR).map(([c, col]) => (
            <span key={c}>
              <i style={{ background: col }} />
              {c}
            </span>
          ))}
        </div>
      </div>
    </>
  );
}
