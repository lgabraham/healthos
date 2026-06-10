import { useEffect, useState } from "react";
import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";
import RecoveryScore from "../components/RecoveryScore.jsx";
import MetricStat from "../components/MetricStat.jsx";
import SleepCard from "../components/SleepCard.jsx";
import EventTimeline from "../components/EventTimeline.jsx";
import CalendarStrip from "../components/CalendarStrip.jsx";
import AttributionPanel from "../components/AttributionPanel.jsx";
import { hm, num } from "../format.js";

function shiftDate(iso, days) {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function todayISO() {
  return new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD, local time
}

function daysAgo(iso, ref) {
  return Math.round((new Date(`${ref}T00:00:00`) - new Date(`${iso}T00:00:00`)) / 86400000);
}

// A stale canonical source quietly degrades half the app (estimated recovery,
// fallback HRV, missing strain). Name it, date it, and print the fix.
function DataHealthBanner({ status }) {
  const [dismissed, setDismissed] = useState(false);
  if (!status?.sources || dismissed) return null;
  const whoop = status.sources.whoop;
  if (!whoop || whoop.days_behind <= 2) return null;
  return (
    <div className="banner" style={{ display: "flex", justifyContent: "space-between", gap: "1rem" }}>
      <span>
        WHOOP LAST RECORDED {whoop.last_data_date} ({whoop.days_behind}d behind) — recovery is
        estimated, strain unavailable. Wear + open the Whoop app, then:{" "}
        <span className="mono">healthos sync --days 30 --source whoop</span>
      </span>
      <button
        onClick={() => setDismissed(true)}
        style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", font: "inherit" }}
        aria-label="dismiss"
      >
        ✕
      </button>
    </div>
  );
}

export default function DailyView() {
  const [date, setDate] = useState(null); // null = latest complete day (server picks)
  const { data: daily, loading, error } = useHealthData(() => api.daily(date), [date]);
  const { data: hrvTrend } = useHealthData(() => api.trend("hrv_rmssd", 30, 7), []);
  const { data: status } = useHealthData(() => api.status(), []);

  const today = todayISO();
  const atToday = daily && daily.date >= today;

  // Keyboard: ←/→ move a day, t jumps to today. Suits the terminal aesthetic.
  useEffect(() => {
    const onKey = (ev) => {
      if (ev.target.tagName === "INPUT" || !daily) return;
      if (ev.key === "ArrowLeft") setDate(shiftDate(daily.date, -1));
      else if (ev.key === "ArrowRight" && !atToday) setDate(shiftDate(daily.date, 1));
      else if (ev.key === "t") setDate(todayISO());
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [daily, atToday]);

  // First load only: bare loader. After that, keep the layout mounted and dim
  // it while fetching, so rapid arrow clicks aren't eaten by an unmount.
  if (!daily && loading) return <div className="muted mono">loading…</div>;
  if (error) return <div className="error">error: {error}</div>;
  if (!daily) return null;

  const m = daily.metrics;
  const spark = (hrvTrend?.series || []).map((d) => d.value);
  const wk = daily.last_workout;
  const wkAge = wk ? daysAgo(wk.date, daily.date) : null;
  const wkStale = wkAge != null && wkAge > 7;

  return (
    <>
      <DataHealthBanner status={status} />
      {daily.building_baseline && (
        <div className="banner">
          BUILDING BASELINE — fewer than 14 days of data. Inference and baselines are provisional.
        </div>
      )}

      <div className="datenav">
        <button onClick={() => setDate(shiftDate(daily.date, -1))} aria-label="previous day">
          ‹
        </button>
        <span className="mono">
          {daily.date}
          {date === null && <span className="muted"> · latest complete day</span>}
        </span>
        <button
          onClick={() => setDate(shiftDate(daily.date, 1))}
          aria-label="next day"
          disabled={atToday}
          style={atToday ? { opacity: 0.3, cursor: "default" } : undefined}
        >
          ›
        </button>
        <button className="ghost" onClick={() => setDate(today)} disabled={daily.date === today}>
          today
        </button>
        <button className="ghost" onClick={() => setDate(null)} disabled={date === null}>
          latest
        </button>
        <span className="muted mono" style={{ fontSize: "0.7rem", marginLeft: "0.5rem" }}>
          ← → t
        </span>
      </div>

      <div style={loading ? { opacity: 0.45, pointerEvents: "none" } : undefined}>
        <div className="grid cols-4">
          <RecoveryScore metric={m.recovery_score} />
          <MetricStat
            label="HRV (nocturnal)"
            metric={m.hrv_rmssd}
            unit="ms"
            spark={spark}
            sparkLabel="last 30d (latest, not this date)"
          />
          <MetricStat label="Resting HR" metric={m.resting_hr} unit="bpm" />
          <MetricStat label="Strain" metric={m.strain_score} digits={1} neutral />
        </div>

        <div className="grid" style={{ marginTop: "0.85rem" }}>
          <AttributionPanel date={daily.date} />
        </div>

        <div className="grid cols-2" style={{ marginTop: "0.85rem" }}>
          <SleepCard sleep={daily.sleep} />
          <EventTimeline events={daily.events} title="Inferred / confirmed events" />
        </div>

        <div className="grid" style={{ marginTop: "0.85rem" }}>
          <CalendarStrip events={daily.calendar} viewDate={daily.date} />
        </div>

        <div className="grid cols-2" style={{ marginTop: "0.85rem" }}>
          <MetricStat label="Steps" metric={m.steps} neutral />
          <div className="panel" style={wkStale ? { opacity: 0.6 } : undefined}>
            <div className="label">Last workout</div>
            {wk ? (
              <>
                <div className="metric-value" style={{ fontSize: "1.2rem" }}>
                  {wk.sport_type || "workout"}
                </div>
                <div className="metric-sub">
                  {wk.date}
                  {wkAge != null &&
                    ` (${wkAge === 0 ? "this day" : wkAge === 1 ? "1 day before" : `${wkAge} days before`})`}
                  {" · "}
                  {hm(wk.duration_minutes)} · avg {num(wk.hr_avg)}bpm · max {num(wk.hr_max)}bpm
                  {wk.distance_km != null ? ` · ${num(wk.distance_km, 1)}km` : ""}
                  {wk.calories != null ? ` · ${num(wk.calories)} cal` : ""}
                  {wk.tss != null ? ` · TSS ${num(wk.tss)}` : ""}
                </div>
              </>
            ) : (
              <div className="metric-sub">No recent workout.</div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
