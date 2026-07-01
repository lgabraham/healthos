import { useState } from "react";
import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";
import { useStepGoal } from "../hooks/useStepGoal.js";
import { Badge } from "@/components/ui/badge";
import { hm, num } from "../format.js";

// A unified workout log: activities recorded by Garmin/Whoop, exercise events
// logged in your calendar, goal+ step days, plus workouts you log by hand here
// when telemetry misses one.
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

function todayISO() {
  return new Date().toLocaleDateString("en-CA");
}

const INPUT = {
  background: "var(--bg)",
  color: "var(--text)",
  border: "1px solid var(--border)",
  borderRadius: 6,
  padding: "0.4rem 0.5rem",
  fontFamily: "var(--mono)",
  fontSize: "0.8rem",
  width: "100%",
  boxSizing: "border-box",
};

function Field({ label, width, children }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: "0.2rem", width }}>
      <span className="muted mono" style={{ fontSize: "0.65rem" }}>
        {label}
      </span>
      {children}
    </label>
  );
}

const EMPTY_FORM = { sport_type: "", date: todayISO(), duration_minutes: "", distance_km: "", calories: "" };

export default function WorkoutsView() {
  const [goal] = useStepGoal(); // shared goal; tuned on the Streak tab
  const [reloadKey, setReloadKey] = useState(0);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState(null);
  const { data: workouts, loading, error } = useHealthData(() => api.workouts(90), [reloadKey]);
  const { data: calendar } = useHealthData(() => api.calendar(90), []);
  const { data: steps } = useHealthData(() => api.trend("steps", 90), []);

  const setField = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submitWorkout = async (e) => {
    e.preventDefault();
    const sport = form.sport_type.trim();
    if (!sport || saving) return;
    setSaving(true);
    setFormError(null);
    try {
      await api.addWorkout({
        sport_type: sport,
        date: form.date || undefined,
        duration_minutes: form.duration_minutes ? Number(form.duration_minutes) : null,
        distance_km: form.distance_km ? Number(form.distance_km) : null,
        calories: form.calories ? Number(form.calories) : null,
      });
      setForm(EMPTY_FORM);
      setShowForm(false);
      setReloadKey((k) => k + 1);
    } catch (err) {
      setFormError(String(err));
    } finally {
      setSaving(false);
    }
  };

  const removeWorkout = async (id) => {
    await api.deleteWorkout(id).catch(() => {});
    setReloadKey((k) => k + 1);
  };

  if (loading) return <div className="muted mono">loading…</div>;
  if (error) return <div className="error">error: {error}</div>;

  const recorded = (workouts || []).map((w) => ({
    kind: "recorded",
    id: w.id,
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

  // Goal+ step days that don't already have a recorded workout — so an active
  // walking day still shows up in the log instead of being blank.
  const workoutDates = new Set(recorded.map((r) => r.date));
  const walked = (steps?.series || [])
    .filter((d) => d.value != null && d.value >= goal && !workoutDates.has(d.date))
    .map((d) => ({ kind: "steps", date: d.date, time: null, label: "Walk", source: "steps", steps: d.value }));

  const all = [...recorded, ...planned, ...walked].sort(
    (a, b) => b.date.localeCompare(a.date) || (b.time || "").localeCompare(a.time || ""),
  );

  // Active days = any day with a recorded workout OR goal+ steps. Scoped to a
  // recent window (older data is sparse/stale, so a /90 count reads low).
  const SUMMARY_DAYS = 30;
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - (SUMMARY_DAYS - 1));
  const cutoffISO = cutoff.toLocaleDateString("en-CA");
  const activeDates = new Set(
    [...workoutDates, ...walked.map((w) => w.date)].filter((d) => d >= cutoffISO),
  );
  const activeCount = activeDates.size;

  return (
    <>
      <div
        className="panel"
        style={{
          marginBottom: "0.8rem",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "0.8rem",
          flexWrap: "wrap",
        }}
      >
        <div>
          <div className="metric-value" style={{ fontSize: "1.4rem" }}>
            {activeCount} <span className="unit">active / {SUMMARY_DAYS} days</span>
          </div>
          <div className="metric-sub">workout or {goal.toLocaleString()}+ steps</div>
        </div>
        <div className="metric-sub mono" style={{ fontSize: "0.68rem", color: "var(--muted)" }}>
          step goal set on the Streak tab
        </div>
      </div>

      <div className="panel" style={{ marginBottom: "0.8rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div className="label">Log a workout manually</div>
          <button className="refresh" onClick={() => setShowForm((s) => !s)}>
            {showForm ? "cancel" : "+ add"}
          </button>
        </div>
        {showForm && (
          <form
            onSubmit={submitWorkout}
            style={{ marginTop: "0.7rem", display: "flex", flexWrap: "wrap", gap: "0.6rem", alignItems: "flex-end" }}
          >
            <Field label="Activity" width="9rem">
              <input
                style={INPUT}
                value={form.sport_type}
                onChange={setField("sport_type")}
                placeholder="run, strength…"
                autoFocus
              />
            </Field>
            <Field label="Date" width="8.5rem">
              <input style={INPUT} type="date" value={form.date} onChange={setField("date")} />
            </Field>
            <Field label="Minutes" width="5rem">
              <input style={INPUT} type="number" min="0" value={form.duration_minutes} onChange={setField("duration_minutes")} />
            </Field>
            <Field label="Km" width="5rem">
              <input style={INPUT} type="number" min="0" step="0.1" value={form.distance_km} onChange={setField("distance_km")} />
            </Field>
            <Field label="Calories" width="5.5rem">
              <input style={INPUT} type="number" min="0" value={form.calories} onChange={setField("calories")} />
            </Field>
            <button className="refresh" type="submit" disabled={saving || !form.sport_type.trim()}>
              {saving ? "saving…" : "log it"}
            </button>
          </form>
        )}
        {formError && (
          <div className="error" style={{ marginTop: "0.5rem" }}>
            error: {formError}
          </div>
        )}
      </div>

      <div className="statusline" style={{ marginBottom: "0.8rem" }}>
        workouts (Garmin/Whoop) + manual entries + calendar exercise + {goal / 1000}k+ step days · last 90 days
      </div>
      {all.length === 0 && (
        <div className="panel">
          <div className="muted mono">
            No workouts in the last 90 days. Garmin/Whoop activities, calendar events tagged exercise
            (gym, yoga, run…), and anything you log above show up here.
          </div>
        </div>
      )}
      <div className="grid" style={{ gap: "0.5rem" }}>
        {all.map((w, i) => (
          <div
            key={w.id || `${w.date}-${i}`}
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
            <div
              className="metric-sub mono"
              style={{ textAlign: "right", display: "flex", alignItems: "center", gap: "0.55rem" }}
            >
              <span>
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
              </span>
              {w.kind === "recorded" && w.source === "manual" && (
                <button
                  onClick={() => removeWorkout(w.id)}
                  title="delete manual workout"
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    color: "var(--muted)",
                    fontSize: "1rem",
                    lineHeight: 1,
                  }}
                >
                  ×
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
