import {
  Area,
  Brush,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { eventColor, eventMeta } from "../format.js";

// Custom-styled Recharts chart: raw daily value (thin), a 7d rolling average
// with a gradient glow, a faint "usual range" channel (your interquartile
// band), behavioral events as colored dots on the line, and a drag Brush.
const AXIS = { stroke: "#3f3f46", fontSize: 11, fontFamily: "IBM Plex Mono" };

function percentile(values, p) {
  if (!values.length) return null;
  const s = [...values].sort((a, b) => a - b);
  const idx = (s.length - 1) * p;
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  return s[lo] + (s[hi] - s[lo]) * (idx - lo);
}

function DarkTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload || {};
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
      {payload
        .filter((p) => p.dataKey === "value" || p.dataKey === "rolling")
        .map((p) => (
          <div key={p.dataKey} style={{ color: p.color }}>
            {p.dataKey}: {p.value == null ? "—" : Number(p.value).toFixed(1)}
          </div>
        ))}
      {row.evtLabel && (
        <div style={{ color: row.evtColor, marginTop: "0.2rem" }}>● {row.evtLabel}</div>
      )}
    </div>
  );
}

function EventDot(props) {
  const { cx, cy, payload } = props;
  if (cx == null || cy == null || !payload?.evtLabel) return null;
  return <circle cx={cx} cy={cy} r={4} fill={payload.evtColor} stroke="#0a0a0a" strokeWidth={1} />;
}

export default function TrendChart({ series, events = [], height = 240, color = "#f59e0b", yFormat }) {
  // Bind events into the data rows (Scatter places reliably on a category
  // axis, unlike ReferenceDot) — the dot rides the value line for that day.
  const evtByDate = {};
  for (const e of events) {
    if (!(e.date in evtByDate)) evtByDate[e.date] = e;
  }
  const data = series.map((d) => {
    const e = evtByDate[d.date];
    const usable = e && d.value != null;
    return {
      ...d,
      evtY: usable ? d.value : null,
      evtLabel: usable ? eventMeta(e.event_type).label : null,
      evtColor: usable ? eventColor(e.event_type) : null,
    };
  });

  // Graded "where you fall" channel from the rolling average's distribution:
  // a darker core (typical, p25–p75) with lighter shoulders (low/high,
  // p10–p25 & p75–p90) and a dashed median line. Outside p10/p90 = unusual.
  const rollVals = data.map((d) => d.rolling).filter((v) => v != null);
  const q = rollVals.length >= 6 ? {
    p10: percentile(rollVals, 0.1),
    p25: percentile(rollVals, 0.25),
    p50: percentile(rollVals, 0.5),
    p75: percentile(rollVals, 0.75),
    p90: percentile(rollVals, 0.9),
  } : null;
  const gradId = `trendGlow-${color.replace("#", "")}`;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.28} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#1f1f1f" vertical={false} />
        {q && q.p90 > q.p10 && (
          <>
            <ReferenceArea y1={q.p10} y2={q.p25} fill={color} fillOpacity={0.06} stroke="none" ifOverflow="extendDomain" />
            <ReferenceArea y1={q.p25} y2={q.p75} fill={color} fillOpacity={0.16} stroke="none" ifOverflow="extendDomain" />
            <ReferenceArea y1={q.p75} y2={q.p90} fill={color} fillOpacity={0.06} stroke="none" ifOverflow="extendDomain" />
            <ReferenceLine y={q.p50} stroke={color} strokeOpacity={0.35} strokeDasharray="3 3" />
          </>
        )}
        <XAxis dataKey="date" tick={AXIS} minTickGap={28} axisLine={AXIS} tickLine={false} />
        <YAxis tick={AXIS} axisLine={AXIS} tickLine={false} width={48} domain={["auto", "auto"]} tickFormatter={yFormat} />
        <Tooltip content={<DarkTooltip />} />
        <Area
          type="monotone"
          dataKey="rolling"
          stroke="none"
          fill={`url(#${gradId})`}
          isAnimationActive={false}
        />
        <Line
          type="linear"
          dataKey="value"
          stroke="#52525b"
          strokeWidth={1}
          dot={false}
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="rolling"
          stroke={color}
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
        />
        <Scatter dataKey="evtY" shape={<EventDot />} isAnimationActive={false} legendType="none" />
        <Brush
          dataKey="date"
          height={20}
          travellerWidth={8}
          stroke="#3f3f46"
          fill="#111111"
          tickFormatter={() => ""}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
