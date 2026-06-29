import { num } from "../format.js";

// A compact multi-day trend snapshot for one metric: the recent 7-day average,
// where it sits vs. the prior baseline (a direction arrow colored by whether
// the move is good FOR YOU — HRV up is good, resting HR up is not), and a
// sparkline showing daily values (faint) under the smoothed rolling line.
function linePath(values, min, max, width, height) {
  const span = max - min || 1;
  const pts = [];
  values.forEach((v, i) => {
    if (v == null) return;
    const x = (i / (values.length - 1)) * width;
    const y = height - ((v - min) / span) * (height - 2) - 1;
    pts.push(`${pts.length === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`);
  });
  return pts.join(" ");
}

function avg(arr) {
  const p = arr.filter((x) => x != null);
  return p.length ? p.reduce((a, b) => a + b, 0) / p.length : null;
}

export default function TrendSnapshot({ label, trend, unit, digits = 0, betterWhen, color }) {
  const series = trend?.series || [];
  const raw = series.map((d) => d.value);
  const rolling = series.map((d) => d.rolling);
  const present = [...raw, ...rolling].filter((x) => x != null);

  if (present.length < 2) {
    return (
      <div className="panel">
        <div className="label">{label}</div>
        <div className="metric-sub" style={{ marginTop: "0.35rem" }}>not enough data yet</div>
      </div>
    );
  }

  const min = Math.min(...present);
  const max = Math.max(...present);

  // Recent 7 days vs. everything before, on the daily values.
  const recent = avg(raw.slice(-7));
  const prior = avg(raw.slice(0, -7));
  const delta = recent != null && prior != null ? recent - prior : null;
  const deltaPct = delta != null && prior ? (delta / prior) * 100 : null;
  const flat = deltaPct == null || Math.abs(deltaPct) < 2;
  const up = delta != null && delta > 0;
  const good = betterWhen === "up" ? up : !up;
  const arrow = flat ? "→" : up ? "↑" : "↓";
  const moveColor = flat ? "var(--muted)" : good ? "var(--good)" : "var(--bad)";

  return (
    <div className="panel">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: "0.5rem" }}>
        <div className="label">{label}</div>
        <div className="mono" style={{ fontSize: "0.72rem", color: moveColor, whiteSpace: "nowrap" }}>
          {arrow} {deltaPct != null ? `${deltaPct > 0 ? "+" : ""}${Math.round(deltaPct)}%` : "—"} vs prior
        </div>
      </div>
      <div className="metric-value" style={{ fontSize: "1.5rem", marginTop: "0.2rem" }}>
        {num(recent, digits)}
        <span className="unit">{unit} · 7d avg</span>
      </div>
      <svg width="100%" height="48" viewBox="0 0 220 48" preserveAspectRatio="none" style={{ marginTop: "0.4rem" }}>
        <path d={linePath(raw, min, max, 220, 48)} fill="none" stroke={color} strokeWidth="1" opacity="0.35" />
        <path d={linePath(rolling, min, max, 220, 48)} fill="none" stroke={color} strokeWidth="2" />
      </svg>
      <div className="muted mono" style={{ fontSize: "0.68rem" }}>
        last {series.length}d · {num(min, digits)}–{num(max, digits)}{unit} · bold = 7d rolling
      </div>
    </div>
  );
}
