import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";
import { Badge } from "@/components/ui/badge";

// A day "counts" if you worked out OR hit the step goal. One rest day is fine;
// two rest days in a row breaks the streak.
const STEP_GOAL = 10000;
const MILESTONES = [5, 10, 20];

const MARK_COLOR = {
  workout: "#4ade80", // trained (green)
  steps: "#f59e0b", // moved, 10k+ (orange)
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
      d.mark = "pending";
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

// Pad to weekday columns: prepend blanks so the first day lands on its weekday
// (Sun=0), then chunk into weeks of 7.
function toWeeks(days) {
  if (!days.length) return [];
  const cells = [];
  const firstDow = new Date(`${days[0].date}T00:00:00`).getDay();
  for (let i = 0; i < firstDow; i++) cells.push(null);
  cells.push(...days);
  const weeks = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

function MilestoneStrip({ streak }) {
  const next = MILESTONES.find((m) => streak < m);
  return (
    <div className="legend" style={{ gap: "1.1rem" }}>
      {MILESTONES.map((m) => {
        const hit = streak >= m;
        const isNext = m === next;
        return (
          <span key={m} style={{ color: hit ? "var(--good)" : isNext ? "var(--accent)" : "var(--muted)" }}>
            {hit ? "🎉" : isNext ? "🎯" : "○"} {m}-day
            {isNext ? ` · ${m - streak} to go` : ""}
          </span>
        );
      })}
    </div>
  );
}

export default function StreakView() {
  const { data: steps, loading, error } = useHealthData(() => api.trend("steps", 90), []);
  const { data: workouts } = useHealthData(() => api.workouts(90), []);

  if (loading) return <div className="muted mono">loading…</div>;
  if (error) return <div className="error">error: {error}</div>;

  const days = buildDays(steps?.series, workouts);
  const { streak, longest } = computeStreak(days);
  const weeks = toWeeks(days);
  const last7 = days.slice(-7);
  const activeThisWeek = last7.filter((d) => d.active).length;
  const justHit = MILESTONES.includes(streak);
  const tier = streak >= 20 ? "🔥 on fire" : streak >= 10 ? "💪 strong" : streak >= 5 ? "✨ rolling" : streak > 0 ? "keep it going" : "start today";

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
          <div className="metric-sub">
            {justHit ? `🎉 just hit ${streak} days!` : streak > 0 ? "days kept going" : "get active today"}
          </div>
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

      <div className="panel" style={{ marginBottom: "0.85rem", display: "flex", alignItems: "center", gap: "0.8rem", flexWrap: "wrap" }}>
        <Badge variant={streak >= 5 ? "default" : "secondary"}>{tier}</Badge>
        <MilestoneStrip streak={streak} />
      </div>

      <div className="panel" style={{ overflowX: "auto" }}>
        <div className="label">Last 90 days</div>
        <div style={{ display: "flex", gap: "3px", marginTop: "0.4rem", width: "max-content" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: "3px", marginRight: "4px" }}>
            {["S", "M", "T", "W", "T", "F", "S"].map((l, i) => (
              <span key={i} style={{ height: 14, fontSize: 9, lineHeight: "14px", color: "var(--muted)", fontFamily: "var(--mono)" }}>
                {i % 2 === 1 ? l : ""}
              </span>
            ))}
          </div>
          {weeks.map((week, wi) => (
            <div key={wi} style={{ display: "flex", flexDirection: "column", gap: "3px" }}>
              {Array.from({ length: 7 }).map((_, di) => {
                const d = week[di];
                if (!d) return <span key={di} style={{ width: 14, height: 14 }} />;
                return (
                  <span
                    key={di}
                    title={`${d.date} · ${markLabel(d)}`}
                    style={{
                      width: 14,
                      height: 14,
                      borderRadius: 2,
                      background: MARK_COLOR[d.mark] || "#1a1a1a",
                      border: d.mark === "rest" || d.mark === "pending" ? "1px solid #3f3f46" : "none",
                    }}
                  />
                );
              })}
            </div>
          ))}
        </div>
        <div className="legend" style={{ marginTop: "0.8rem" }}>
          <span><i style={{ background: MARK_COLOR.workout }} />workout</span>
          <span><i style={{ background: MARK_COLOR.steps }} />10k+ steps</span>
          <span><i style={{ background: MARK_COLOR.rest, border: "1px solid #3f3f46" }} />rest (ok)</span>
          <span><i style={{ background: MARK_COLOR.broken }} />broke streak</span>
        </div>
      </div>
    </>
  );
}
