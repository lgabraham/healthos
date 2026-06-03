import { num } from "../format.js";

// Large, prominent recovery readout (Whoop). Color tracks Whoop's zones.
function zone(score) {
  if (score == null) return "var(--muted)";
  if (score >= 67) return "var(--good)";
  if (score >= 34) return "var(--warn)";
  return "var(--bad)";
}

export default function RecoveryScore({ metric }) {
  const v = metric?.value;
  return (
    <div className="panel" style={{ gridColumn: "span 1" }}>
      <div className="label">Recovery</div>
      <div className="metric-value xl" style={{ color: zone(v) }}>
        {num(v)}
        <span className="unit">%</span>
      </div>
      <div className="metric-sub">
        {metric?.baseline != null ? `30d avg ${num(metric.baseline)}%` : "no baseline yet"}
        {metric && !metric.baseline_trustworthy ? " · building baseline" : ""}
      </div>
    </div>
  );
}
