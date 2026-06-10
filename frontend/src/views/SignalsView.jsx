import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";

// HRV + resting HR over time, with calendar events overlaid as dots colored by
// TYPE (titles stay local-only). Lets you eyeball "drinks night -> HRV dip".
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

function category(keywords) {
  return (keywords && keywords[0]) || "other";
}

export default function SignalsView() {
  const days = 60;
  const { data: hrv, loading, error } = useHealthData(() => api.trend("hrv_rmssd", days, 7), []);
  const { data: rhr } = useHealthData(() => api.trend("resting_hr", days, 7), []);
  const { data: cal } = useHealthData(() => api.calendar(days), []);

  if (loading) return <div className="muted mono">loading…</div>;
  if (error) return <div className="error">error: {error}</div>;

  const hrvByDate = Object.fromEntries((hrv?.series || []).map((d) => [d.date, d.value]));
  const rhrByDate = Object.fromEntries((rhr?.series || []).map((d) => [d.date, d.value]));
  const events = (cal || []).filter((e) => !e.all_day);

  // X axis = union of metric dates + event dates, so every event has a slot.
  const dates = Array.from(
    new Set([...Object.keys(hrvByDate), ...events.map((e) => e.date)])
  ).sort();
  const merged = dates.map((date) => ({
    date,
    hrv: hrvByDate[date] ?? null,
    rhr: rhrByDate[date] ?? null,
  }));
  const hrvValues = merged.map((d) => d.hrv).filter((v) => v != null);
  const hrvFloor = hrvValues.length ? Math.min(...hrvValues) : 0;
  const dateSet = new Set(dates);

  return (
    <>
      <div className="statusline" style={{ marginBottom: "0.8rem" }}>
        HRV (amber) + resting HR (blue) · {days}d · calendar events as dots by type · titles local
        only
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
            <Tooltip
              contentStyle={{
                background: "#181818",
                border: "1px solid #262626",
                fontFamily: "IBM Plex Mono",
                fontSize: 12,
              }}
            />
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
            {events
              .filter((e) => dateSet.has(e.date))
              .map((e, i) => (
                <ReferenceDot
                  key={`${e.date}-${i}`}
                  yAxisId="hrv"
                  x={e.date}
                  y={hrvFloor}
                  r={4}
                  fill={CAT_COLOR[category(e.keywords)]}
                  stroke="#0a0a0a"
                  strokeWidth={1}
                  ifOverflow="extendDomain"
                >
                  <title>{`${e.date} · ${category(e.keywords)} · ${e.title || ""}`}</title>
                </ReferenceDot>
              ))}
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
