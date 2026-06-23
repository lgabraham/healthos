import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";
import { Badge } from "@/components/ui/badge";
import { hm, num } from "../format.js";

// A unified workout log: activities recorded by Garmin/Whoop plus exercise
// events logged in your calendar, newest first.
function relDay(dateStr) {
  const d = new Date(`${dateStr}T00:00:00`);
  const diff = Math.round((new Date().setHours(0, 0, 0, 0) - d) / 86400000);
  if (diff <= 0) return "today";
  if (diff === 1) return "yesterday";
  if (diff < 7) return `${diff}d ago`;
  if (diff < 14) return "1w ago";
  return `${Math.floor(diff / 7)}w ago`;
}

function fmtTime(iso) {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  } catch {
    return null;
  }
}

const STEP_GOAL = 10000;

export default function WorkoutsView() {
  const { data: workouts, loading, error } = useHealthData(() => api.workouts(90), []);
  const { data: calendar } = useHealthData(() => api.calendar(90), []);
  const { data: steps } = useHealthData(() => api.trend("steps", 90), []);

  if (loading) return <div className="muted mono">loading…</div>;
  if (error) return <div className="error">error: {error}</div>;

  const recorded = (workouts || []).map((w) => ({
    kind: "recorded",
    date: w.date,
    time: w.start_time,
    label: (w.sport_type || "workout").replace(/_/g, " "),
    source: w.source,
    duration: w.duration_minutes,
    hr_avg: w.hr_avg,
    hr_max: w.hr_max,
    distance: w.distance_km,
    calories: w.calories,
    tss: w.tss,
  }));
  // Calendar planning/reminder entries that aren't actual workouts.
  const IGNORE_TITLES = ["plan workout", "workout plan"];
  const planned = (calendar || [])
    .filter((e) => (e.keywords || []).includes("exercise"))
    .filter((e) => {
      const t = (e.title || "").toLowerCase();
      return !IGNORE_TITLES.some((p) => t.includes(p));
    })
    .map((e) => ({
      kind: "planned",
      date: e.date,
      time: e.start_time,
      label: e.title || "exercise",
      source: "calendar",
    }));

  // 10k+ step days that don't already have a recorded workout — so an active
  // walking day still shows up in the log instead of being blank.
  const workoutDates = new Set(recorded.map((r) => r.date));
  const walked = (steps?.series || [])
    .filter((d) => d.value != null && d.value >= STEP_GOAL && !workoutDates.has(d.date))
    .map((d) => ({ kind: "steps", date: d.date, time: null, label: "Walk", source: "steps", steps: d.value }));

  const all = [...recorded, ...planned, ...walked].sort(
    (a, b) => b.date.localeCompare(a.date) || (b.time || "").localeCompare(a.time || ""),
  );

  return (
    <>
      <div className="statusline" style={{ marginBottom: "0.8rem" }}>
        workouts (Garmin/Whoop) + calendar exercise + 10k+ step days · last 90 days
      </div>
      {all.length === 0 && (
        <div className="panel">
          <div className="muted mono">
            No workouts in the last 90 days. Garmin activities and calendar events tagged exercise
            (gym, yoga, run…) show up here.
          </div>
        </div>
      )}
      <div className="grid" style={{ gap: "0.5rem" }}>
        {all.map((w, i) => (
          <div
            key={`${w.date}-${i}`}
            className="panel"
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: "0.6rem",
            }}
          >
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <span className="metric-value" style={{ fontSize: "1.05rem", textTransform: "capitalize" }}>
                  {w.label}
                </span>
                <Badge variant={w.kind === "recorded" ? "outline" : "secondary"}>{w.source}</Badge>
              </div>
              <div className="metric-sub">
                {w.date} · {relDay(w.date)}
                {fmtTime(w.time) ? ` · ${fmtTime(w.time)}` : ""}
              </div>
            </div>
            <div className="metric-sub mono" style={{ textAlign: "right" }}>
              {w.kind === "recorded" ? (
                <>
                  {w.duration ? hm(w.duration) : "—"}
                  {w.hr_avg != null ? ` · avg ${num(w.hr_avg)}bpm` : ""}
                  {w.hr_max != null ? ` · max ${num(w.hr_max)}bpm` : ""}
                  {w.distance != null ? ` · ${num(w.distance, 1)}km` : ""}
                  {w.calories != null ? ` · ${num(w.calories)} cal` : ""}
                  {w.tss != null ? ` · TSS ${num(w.tss)}` : ""}
                </>
              ) : w.kind === "steps" ? (
                `${Math.round(w.steps).toLocaleString()} steps`
              ) : (
                <span className="muted">logged in calendar</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
