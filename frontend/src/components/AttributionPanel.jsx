import {
  Bar,
  BarChart,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";

// "Why is today what it is" — each bar is the metric's SIGNED DEVIATION from
// its own 30-day baseline (left = below your normal, right = above), while
// COLOR says what that means for recovery (amber = helps, red = hurts,
// gray = neutral, e.g. strain). One axis semantic, one color semantic.
const AXIS = { stroke: "#3f3f46", fontSize: 11, fontFamily: "IBM Plex Mono" };

function barColor(d) {
  if (d.neutral) return "#52525b";
  return d.pct >= 0 ? "#f59e0b" : "#ef4444";
}

export default function AttributionPanel({ date }) {
  const { data, loading, error } = useHealthData(() => api.attribution(date), [date]);

  if (loading) return <div className="panel"><div className="label">Why today</div><div className="muted mono">loading…</div></div>;
  if (error) return <div className="panel"><div className="label">Why today</div><div className="error">error: {error}</div></div>;
  if (!data || data.drivers.length === 0) {
    return (
      <div className="panel">
        <div className="label">Why today</div>
        <div className="metric-sub">{data?.reason || "Nothing to attribute for this day."}</div>
      </div>
    );
  }

  const rows = data.drivers.map((d) => ({
    ...d,
    name: `${d.label}${d.is_fallback ? " *" : ""}`,
  }));

  return (
    <div className="panel">
      <div className="label">Why today</div>
      {data.headline && (
        <div
          className="mono"
          style={{ fontSize: "0.82rem", color: "var(--accent)", marginBottom: "0.3rem" }}
        >
          {data.headline}
        </div>
      )}
      {data.events.length > 0 && (
        <div className="metric-sub" style={{ marginBottom: "0.4rem" }}>
          context: {data.events.join(" · ")}
        </div>
      )}
      <ResponsiveContainer width="100%" height={Math.max(140, rows.length * 34)}>
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
          <XAxis
            type="number"
            tick={AXIS}
            tickLine={false}
            axisLine={AXIS}
            unit="%"
            // Always include 0 and at least ±5%, so "close to baseline" LOOKS
            // close to baseline instead of bars pinned across a 0.7–3.5% axis.
            domain={[(dataMin) => Math.min(-5, Math.floor(dataMin)), (dataMax) => Math.max(5, Math.ceil(dataMax))]}
          />
          <YAxis
            type="category"
            dataKey="name"
            width={130}
            tick={{ ...AXIS, fontSize: 11 }}
            tickLine={false}
            axisLine={false}
          />
          <ReferenceLine x={0} stroke="#3f3f46" />
          <Tooltip
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
            contentStyle={{
              background: "#181818",
              border: "1px solid #262626",
              fontFamily: "IBM Plex Mono",
              fontSize: 12,
            }}
            formatter={(v, _n, { payload }) => [
              `${v > 0 ? "+" : ""}${v}% vs base ${payload.baseline} (now ${payload.value}) — ${
                payload.neutral ? "neutral" : payload.pct >= 0 ? "helps recovery" : "drags recovery"
              }`,
              payload.label,
            ]}
          />
          <Bar dataKey="deviation_pct" isAnimationActive={false} barSize={14}>
            {rows.map((d) => (
              <Cell key={d.key} fill={barColor(d)} opacity={d.is_fallback ? 0.55 : 1} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="metric-sub">
        bar = deviation from your 30d baseline · color: amber helps recovery, red hurts, gray
        neutral · * fallback source
      </div>
    </div>
  );
}
