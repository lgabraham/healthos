import { sparkPath } from "./Sparkline.jsx";
import { deltaClass, deltaLabel, num } from "../format.js";

// Compact metric tile: value, unit, baseline delta, and an optional sparkline.
// `neutral` suppresses good/bad coloring for metrics with no universally bad
// direction (low strain = rest day; fewer steps isn't a health failure).
export default function MetricStat({ label, metric, unit, digits = 0, spark, sparkLabel, neutral }) {
  const v = metric?.value;
  return (
    <div className="panel">
      <div className="label">{label}</div>
      <div className="metric-value">
        {num(v, digits)}
        {unit && <span className="unit">{unit}</span>}
      </div>
      <div className="metric-sub">
        {v == null ? (
          "no data for this day"
        ) : metric?.is_fallback ? (
          <span style={{ color: "var(--accent)" }}>via {metric.source} (fallback)</span>
        ) : metric?.baseline != null ? (
          <>
            base {num(metric.baseline, digits)}{" "}
            <span className={neutral ? "muted" : deltaClass(metric.delta_pct)}>
              {deltaLabel(metric.delta_pct)}
            </span>
          </>
        ) : (
          "no baseline yet"
        )}
      </div>
      {spark && spark.length > 1 && (
        <>
          <svg width="100%" height="28" viewBox="0 0 100 28" preserveAspectRatio="none">
            <path
              d={sparkPath(spark, 100, 28)}
              fill="none"
              stroke="var(--accent)"
              strokeWidth="1.5"
            />
          </svg>
          {sparkLabel && (
            <div className="muted mono" style={{ fontSize: "0.62rem" }}>
              {sparkLabel}
            </div>
          )}
        </>
      )}
    </div>
  );
}
