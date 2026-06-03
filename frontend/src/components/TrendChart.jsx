import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { eventColor, eventMeta } from "../format.js";

// Custom-styled Recharts line chart: raw value (thin) + rolling average (amber),
// with behavioral events drawn as colored dots pinned to the x-axis.
const AXIS = { stroke: "#3f3f46", fontSize: 11, fontFamily: "IBM Plex Mono" };

function DarkTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
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
      {payload.map((p) => (
        <div key={p.dataKey} style={{ color: p.color }}>
          {p.dataKey}: {p.value == null ? "—" : Number(p.value).toFixed(1)}
        </div>
      ))}
    </div>
  );
}

export default function TrendChart({ series, events = [], height = 240, color = "#f59e0b" }) {
  const yByDate = Object.fromEntries(series.map((d) => [d.date, d.value]));
  const eventDots = events
    .filter((e) => yByDate[e.date] != null)
    .map((e) => ({ ...e, y: yByDate[e.date] }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={series} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
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
        {eventDots.map((e, i) => (
          <ReferenceDot
            key={`${e.event_type}-${e.date}-${i}`}
            x={e.date}
            y={e.y}
            r={4}
            fill={eventColor(e.event_type)}
            stroke="#0a0a0a"
            strokeWidth={1}
            ifOverflow="extendDomain"
          >
            <title>{eventMeta(e.event_type).label}</title>
          </ReferenceDot>
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
