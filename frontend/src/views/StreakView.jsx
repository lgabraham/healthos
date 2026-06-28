import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";
import { useStepGoal, STEP_GOALS } from "../hooks/useStepGoal.js";
import { useSkipDays, SKIP_DAYS } from "../hooks/useSkipDays.js";
import { Badge } from "@/components/ui/badge";

// A day "counts" if you worked out OR hit the step goal. Up to `allowedSkips`
// weekday rest days in a row are forgiven (weekends are always free); the next
// consecutive weekday rest breaks the streak.
const MILESTONES = [5, 10, 20];

const MARK_COLOR = {
  workout: "#4ade80", // trained (green)
  steps: "#f59e0b", // moved, 10k+ (orange)
  rest: "#2f2f33", // single weekday rest — streak held
  weekend: "#2a2d36", // weekend rest — free, never breaks
  broken: "#5b1a1a", // 2nd weekday rest in a row — streak broke
  pending: "#1a1a1a", // today, not yet active
};

function todayISO() {
  return new Date().toLocaleDateString("en-CA");
}

function buildDays(stepsSeries, workouts, goal) {
  const workoutDays = new Set((workouts || []).map((w) => w.date));
  return (stepsSeries || []).map((d) => {
    const worked = workoutDays.has(d.date);
    const hitGoal = d.value != null && d.value >= goal;
    return { date: d.date, steps: d.value, worked, hitGoal, active: worked || hitGoal };
  });
}

function computeStreak(days, allowedSkips) {
  const today = todayISO();
  let streak = 0;
  let longest = 0;
  let restRun = 0; // consecutive weekday rest days (weekends don't count)
  for (const d of days) {
    const dow = new Date(`${d.date}T00:00:00`).getDay();
    const weekend = dow === 0 || dow === 6;
    if (d.date === today && !d.active) {
      d.mark = "pending";
      continue;
    }
    if (d.active) {
      streak += 1;
      restRun = 0;
      d.mark = d.worked ? "workout" : "steps";
    } else if (weekend) {
      // Weekends are free: never break, and don't use up an allowed skip.
      streak += 1;
      d.mark = "weekend";
    } else if (++restRun > allowedSkips) {
      streak = 0;
      d.mark = "broken";
    } else {
      streak += 1;
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
  if (d.mark === "weekend") return "weekend (free)";
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
  const [goal, setGoal] = useStepGoal();
  const [skipDays, setSkipDays] = useSkipDays();
  const { data: steps, loading, error } = useHealthData(() => api.trend("steps", 90), []);
  const { data: workouts } = useHealthData(() => api.workouts(90), []);

  if (loading) return <div className="muted mono">loading…</div>;
  if (error) return <div className="error">error: {error}</div>;

  const days = buildDays(steps?.series, workouts, goal);
  const { streak, longest } = computeStreak(days, skipDays);
  const weeks = toWeeks(days);
  const last7 = days.slice(-7);
  const activeThisWeek = last7.filter((d) => d.active).length;
  const justHit = MILESTONES.includes(streak);
  const tier = streak >= 20 ? "🔥 on fire" : streak >= 10 ? "💪 strong" : streak >= 5 ? "✨ rolling" : streak > 0 ? "keep it going" : "start today";

  return (
    // order: graph (1) → streak stats (2,3) → the rules + step-goal toggle (4)
    <div style={{ display: "flex", flexDirection: "column" }}>
      <div
        className="statusline"
        style={{ order: 4, marginBottom: 0, marginTop: "0.85rem", display: "flex", alignItems: "center", gap: "0.7rem", flexWrap: "wrap" }}
      >
        <span>
          a day counts if you worked out or hit {goal.toLocaleString()} steps ·{" "}
          {skipDays === 0
            ? "every weekday must count"
            : `up to ${skipDays} weekday skip${skipDays > 1 ? "s" : ""} in a row is fine`}{" "}
          · weekends are free
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
          <span className="muted" style={{ fontSize: "0.72rem" }}>steps</span>
          <div className="toggle">
            {STEP_GOALS.map((g) => (
              <button key={g} className={goal === g ? "active" : ""} onClick={() => setGoal(g)}>
                {g / 1000}k
              </button>
            ))}
          </div>
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
          <span className="muted" style={{ fontSize: "0.72rem" }}>skip days</span>
          <div className="toggle">
            {SKIP_DAYS.map((n) => (
              <button key={n} className={skipDays === n ? "active" : ""} onClick={() => setSkipDays(n)}>
                {n}
              </button>
            ))}
          </div>
        </span>
      </div>

      <div className="grid cols-3" style={{ order: 2, marginBottom: "0.85rem" }}>
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

      <div className="panel" style={{ order: 3, marginBottom: "0.85rem", display: "flex", alignItems: "center", gap: "0.8rem", flexWrap: "wrap" }}>
        <Badge variant={streak >= 5 ? "default" : "secondary"}>{tier}</Badge>
        <MilestoneStrip streak={streak} />
      </div>

      <div className="panel" style={{ order: 1, marginBottom: "0.85rem", overflowX: "auto" }}>
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
          <span><i style={{ background: MARK_COLOR.steps }} />{goal / 1000}k+ steps</span>
          <span><i style={{ background: MARK_COLOR.rest, border: "1px solid #3f3f46" }} />rest (ok)</span>
          <span><i style={{ background: MARK_COLOR.broken }} />broke streak</span>
        </div>
      </div>
    </div>
  );
}
