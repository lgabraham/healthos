import {
  Brush,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { eventColor, eventMeta } from "../format.js";

// Custom-styled Recharts line chart: raw value (thin) + rolling average (amber),
// with behavioral events as colored dots riding the value line, and a drag
// handle (Brush) to scroll/zoom the time window.
const AXIS = { stroke: "#3f3f46", fontSize: 11, fontFamily: "IBM Plex Mono" };

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

export default function TrendChart({ series, events = [], height = 240, color = "#f59e0b" }) {
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

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
        <CartesianGrid stroke="#1f1f1f" vertical={false} />
        <XAxis dataKey="date" tick={AXIS} minTickGap={28} axisLine={AXIS} tickLine={false} />
        <YAxis tick={AXIS} axisLine={AXIS} tickLine={false} width={42} domain={["auto", "auto"]} />
        <Tooltip content={<DarkTooltip />} />
        <Line
          type="monotone"
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
