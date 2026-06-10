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

// "Why is today what it is" — signed deviations from personal baselines.
// Positive (amber) = helping recovery; negative (red) = dragging it down.
const AXIS = { stroke: "#3f3f46", fontSize: 11, fontFamily: "IBM Plex Mono" };

export default function AttributionPanel({ date }) {
  const { data, loading, error } = useHealthData(() => api.attribution(date), [date]);

  if (loading) return <div className="panel"><div className="label">Why today</div><div className="muted mono">loading…</div></div>;
  if (error) return <div className="panel"><div className="label">Why today</div><div className="error">error: {error}</div></div>;
  if (!data || data.drivers.length === 0) {
    return (
      <div className="panel">
        <div className="label">Why today</div>
        <div className="metric-sub">Not enough baseline data to attribute yet.</div>
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
            domain={["auto", "auto"]}
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
              `${v > 0 ? "+" : ""}${v}% (now ${payload.value} vs base ${payload.baseline})`,
              payload.label,
            ]}
          />
          <Bar dataKey="pct" isAnimationActive={false} barSize={14}>
            {rows.map((d) => (
              <Cell
                key={d.key}
                fill={d.pct >= 0 ? "#f59e0b" : "#ef4444"}
                opacity={d.is_fallback ? 0.55 : 1}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="metric-sub">deviation from your 30d baseline · + helps recovery · * fallback source</div>
    </div>
  );
}
