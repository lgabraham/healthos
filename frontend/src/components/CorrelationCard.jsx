import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";

const AXIS = { stroke: "#3f3f46", fontSize: 11, fontFamily: "IBM Plex Mono" };

// One correlation card: scatter plot + r + sample size + plain-language read.
export default function CorrelationCard({ card }) {
  const points = card.points || [];
  const degenerate = card.degenerate || card.r == null || points.length === 0;
  if (degenerate) {
    return (
      <div className="panel">
        <div className="label">{card.title}</div>
        <div className="corr-r" style={{ marginBottom: "0.4rem" }}>r = —</div>
        <div className="metric-sub">{card.interpretation}</div>
      </div>
    );
  }
  return (
    <div className="panel">
      <div className="label">{card.title}</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: "0.8rem" }}>
        <span className="corr-r">r = {card.r.toFixed(2)}</span>
        <span className="metric-sub">n = {card.n}</span>
      </div>
      <ResponsiveContainer width="100%" height={160}>
        <ScatterChart margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
          <CartesianGrid stroke="#1f1f1f" />
          <XAxis
            type="number"
            dataKey="x"
            name={card.metric_a}
            tick={AXIS}
            axisLine={AXIS}
            tickLine={false}
          />
          <YAxis
            type="number"
            dataKey="y"
            name={card.metric_b}
            tick={AXIS}
            axisLine={AXIS}
            tickLine={false}
            width={42}
          />
          <ZAxis range={[40, 40]} />
          <Tooltip
            cursor={{ stroke: "#262626" }}
            contentStyle={{
              background: "#181818",
              border: "1px solid #262626",
              fontFamily: "IBM Plex Mono",
              fontSize: 12,
            }}
          />
          <Scatter data={points} fill="#f59e0b" isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
      <div className="metric-sub" style={{ marginTop: "0.5rem" }}>
        {card.interpretation}
      </div>
    </div>
  );
}
