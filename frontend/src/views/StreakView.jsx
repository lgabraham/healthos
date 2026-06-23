import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";
import { Badge } from "@/components/ui/badge";

// A day "counts" if you worked out OR hit the step goal. One rest day is fine;
// two rest days in a row breaks the streak.
const STEP_GOAL = 10000;

const MARK_COLOR = {
  workout: "#f59e0b", // trained
  steps: "#4ade80", // moved (10k+)
  rest: "#2f2f33", // single rest — streak held
  broken: "#5b1a1a", // 2nd rest in a row — streak broke
  pending: "#1a1a1a", // today, not yet active
};

function todayISO() {
  return new Date().toLocaleDateString("en-CA");
}

function buildDays(stepsSeries, workouts) {
  const workoutDays = new Set((workouts || []).map((w) => w.date));
  return (stepsSeries || []).map((d) => {
    const worked = workoutDays.has(d.date);
    const hit10k = d.value != null && d.value >= STEP_GOAL;
    return { date: d.date, steps: d.value, worked, hit10k, active: worked || hit10k };
  });
}

function computeStreak(days) {
  const today = todayISO();
  let streak = 0;
  let longest = 0;
  let prevRest = false;
  for (const d of days) {
    if (d.date === today && !d.active) {
      d.mark = "pending"; // don't let an incomplete today break the streak
      continue;
    }
    if (d.active) {
      streak += 1;
      prevRest = false;
      d.mark = d.worked ? "workout" : "steps";
    } else if (prevRest) {
      streak = 0;
      d.mark = "broken";
    } else {
      streak += 1;
      prevRest = true;
      d.mark = "rest";
    }
    longest = Math.max(longest, streak);
  }
  return { streak, longest };
}

function markLabel(d) {
  if (d.mark === "workout") return "workout";
  if (d.mark === "steps") return `${Math.round(d.steps).toLocaleString()} steps`;
  if (d.mark === "broken") return "rest (streak broke)";
  if (d.mark === "pending") return "today — not active yet";
  return d.steps != null ? `rest · ${Math.round(d.steps).toLocaleString()} steps` : "rest";
}

export default function StreakView() {
  const { data: steps, loading, error } = useHealthData(() => api.trend("steps", 90), []);
  const { data: workouts } = useHealthData(() => api.workouts(90), []);

  if (loading) return <div className="muted mono">loading…</div>;
  if (error) return <div className="error">error: {error}</div>;

  const days = buildDays(steps?.series, workouts);
  const { streak, longest } = computeStreak(days);
  const last7 = days.slice(-7);
  const activeThisWeek = last7.filter((d) => d.active).length;

  return (
    <>
      <div className="statusline" style={{ marginBottom: "0.8rem" }}>
        a day counts if you worked out or hit {STEP_GOAL.toLocaleString()} steps · one rest is fine,
        two in a row breaks it
      </div>

      <div className="grid cols-3" style={{ marginBottom: "0.85rem" }}>
        <div className="panel hero">
          <div className="label">Current streak</div>
          <div className="metric-value xl" style={{ color: streak > 0 ? "var(--accent)" : "var(--muted)" }}>
            🔥 {streak}
          </div>
          <div className="metric-sub">days kept going</div>
        </div>
        <div className="panel hero">
          <div className="label">Longest streak</div>
          <div className="metric-value xl">{longest}</div>
          <div className="metric-sub">your record (last 90d)</div>
        </div>
        <div className="panel hero">
          <div className="label">This week</div>
          <div className="metric-value xl">{activeThisWeek}<span className="unit">/7</span></div>
          <div className="metric-sub">active days</div>
        </div>
      </div>

      <div className="panel">
        <div className="label">Last 90 days</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "3px", marginTop: "0.4rem" }}>
          {days.map((d) => (
            <span
              key={d.date}
              title={`${d.date} · ${markLabel(d)}`}
              style={{
                width: 14,
                height: 14,
                borderRadius: 2,
                background: MARK_COLOR[d.mark] || "#1a1a1a",
                border: d.mark === "rest" || d.mark === "pending" ? "1px solid #3f3f46" : "none",
              }}
            />
          ))}
        </div>
        <div className="legend" style={{ marginTop: "0.8rem" }}>
          <span><i style={{ background: MARK_COLOR.workout }} />workout</span>
          <span><i style={{ background: MARK_COLOR.steps }} />10k+ steps</span>
          <span><i style={{ background: MARK_COLOR.rest, border: "1px solid #3f3f46" }} />rest (ok)</span>
          <span><i style={{ background: MARK_COLOR.broken }} />broke streak</span>
        </div>
      </div>

      <div className="panel" style={{ marginTop: "0.85rem", display: "flex", alignItems: "center", gap: "0.6rem", flexWrap: "wrap" }}>
        <Badge variant={streak >= 7 ? "default" : "secondary"}>
          {streak >= 14 ? "🔥 on fire" : streak >= 7 ? "strong week+" : streak > 0 ? "keep it going" : "start today"}
        </Badge>
        <span className="metric-sub">
          {last7.length ? `${activeThisWeek} of the last 7 days active.` : ""}{" "}
          {streak > 0 && days[days.length - 1]?.mark === "rest"
            ? "Resting today — get active tomorrow to keep the streak alive."
            : ""}
        </span>
      </div>
    </>
  );
}
