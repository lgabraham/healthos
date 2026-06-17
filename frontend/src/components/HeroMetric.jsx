import { sparkPath } from "./Sparkline.jsx";
import { num } from "../format.js";

// Big, calm landing-page tile: the number, a one-line context, and a recent
// trend line that ENDS on the viewed date (so it actually reflects the day
// you're looking at, not just "latest"). Used for the three headline signals.
export default function HeroMetric({ label, metric, unit, digits = 0, trend, color }) {
  const v = metric?.value;
  const vals = (trend || []).map((d) => d.value);
  const present = vals.filter((x) => x != null);
  const lo = present.length ? Math.min(...present) : null;
  const hi = present.length ? Math.max(...present) : null;

  const sub =
    v == null
      ? "no data for this day"
      : metric?.is_fallback
        ? `via ${metric.source} (fallback)`
        : metric?.baseline != null
          ? `30d avg ${num(metric.baseline, digits)}${unit}`
          : "no baseline yet";

  return (
    <div className="panel hero">
      <div className="label">{label}</div>
      <div className="metric-value xl" style={v == null ? { color: "var(--muted)" } : undefined}>
        {num(v, digits)}
        {v != null && <span className="unit">{unit}</span>}
      </div>
      <div className="metric-sub">{sub}</div>
      {present.length > 1 && (
        <div className="hero-trend">
          <svg width="100%" height="46" viewBox="0 0 220 46" preserveAspectRatio="none">
            <path d={sparkPath(vals, 220, 46)} fill="none" stroke={color || "var(--accent)"} strokeWidth="2" />
          </svg>
          <div className="muted mono hero-trend-cap">
            last {trend.length}d · {num(lo, digits)}–{num(hi, digits)}{unit}
          </div>
        </div>
      )}
    </div>
  );
}
