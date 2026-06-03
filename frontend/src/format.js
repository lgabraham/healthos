// Formatting + presentation helpers shared across views.

export function hm(minutes) {
  if (minutes == null) return "—";
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return `${h}h ${String(m).padStart(2, "0")}m`;
}

export function num(v, digits = 0) {
  if (v == null) return "—";
  return Number(v).toFixed(digits);
}

export function deltaClass(pct) {
  if (pct == null) return "";
  return pct >= 0 ? "delta up" : "delta down";
}

export function deltaLabel(pct) {
  if (pct == null) return "";
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}

// Badge presentation for each behavioral event type.
const EVENT_META = {
  alcohol_detected: { icon: "🟡", label: "alcohol detected" },
  sick: { icon: "🔴", label: "sick" },
  late_workout: { icon: "🟠", label: "late workout" },
  travel: { icon: "✈️", label: "travel" },
  high_stress_day: { icon: "🟣", label: "high stress" },
  sauna: { icon: "🔥", label: "sauna" },
  elevated_screen_time: { icon: "📱", label: "screen time" },
  calendar_heavy_day: { icon: "📅", label: "calendar heavy" },
};

export function eventMeta(type) {
  return EVENT_META[type] || { icon: "⚪", label: type.replace(/_/g, " ") };
}

// Stable color per event type for chart x-axis markers.
const EVENT_COLOR = {
  alcohol_detected: "#f59e0b",
  sick: "#ef4444",
  late_workout: "#fb923c",
  travel: "#38bdf8",
  high_stress_day: "#a855f7",
  sauna: "#f97316",
};

export function eventColor(type) {
  return EVENT_COLOR[type] || "#8a8a8a";
}
