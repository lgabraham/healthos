import { sparkPath } from "./Sparkline.jsx";
import { deltaClass, deltaLabel, num } from "../format.js";

// Compact metric tile: value, unit, baseline delta, and an optional sparkline.
export default function MetricStat({ label, metric, unit, digits = 0, spark }) {
  const v = metric?.value;
  return (
    <div className="panel">
      <div className="label">{label}</div>
      <div className="metric-value">
        {num(v, digits)}
        {unit && <span className="unit">{unit}</span>}
      </div>
      <div className="metric-sub">
        {metric?.baseline != null ? (
          <>
            base {num(metric.baseline, digits)}{" "}
            <span className={deltaClass(metric.delta_pct)}>{deltaLabel(metric.delta_pct)}</span>
          </>
        ) : (
          "no baseline"
        )}
      </div>
      {spark && spark.length > 1 && (
        <svg width="100%" height="28" viewBox="0 0 100 28" preserveAspectRatio="none">
          <path
            d={sparkPath(spark, 100, 28)}
            fill="none"
            stroke="var(--accent)"
            strokeWidth="1.5"
          />
        </svg>
      )}
    </div>
  );
}
