import { useEffect, useState } from "react";
import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";
import RecoveryScore from "../components/RecoveryScore.jsx";
import MetricStat from "../components/MetricStat.jsx";
import HeroMetric from "../components/HeroMetric.jsx";
import TrendSnapshot from "../components/TrendSnapshot.jsx";
import SleepCard from "../components/SleepCard.jsx";
import EventTimeline from "../components/EventTimeline.jsx";
import CalendarStrip from "../components/CalendarStrip.jsx";
import AttributionPanel from "../components/AttributionPanel.jsx";
import DatePicker from "../components/DatePicker.jsx";
import { useStepGoal } from "../hooks/useStepGoal.js";
import { useSkipDays } from "../hooks/useSkipDays.js";
import { useRhrOffset } from "../hooks/useRhrOffset.js";
import { activityStreak, sleepStreak } from "../lib/streaks.js";
import { hm, num } from "../format.js";

function shiftDate(iso, days) {
  // Parse AND serialize in local time. Using toISOString() here (UTC) while
  // parsing local midnight shifted the result by a day in any UTC+ timezone,
  // which broke the next/prev-day buttons east of Greenwich.
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return d.toLocaleDateString("en-CA"); // YYYY-MM-DD, local time
}

function todayISO() {
  return new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD, local time
}

function daysAgo(iso, ref) {
  return Math.round((new Date(`${ref}T00:00:00`) - new Date(`${iso}T00:00:00`)) / 86400000);
}

// Trailing slice of a trend series ending ON the viewed date (so the hero
// sparkline reflects the day you're looking at, not just the newest data).
function trendUpTo(trend, date, n = 21) {
  return (trend?.series || []).filter((d) => d.date <= date).slice(-n);
}

// Warn only when your PRIMARY nightly source (the pod) goes silent — and stay
// quiet when Whoop is covering (e.g. travel). No more nagging about stale
// Whoop, which is just the fallback now.
function DataHealthBanner({ status }) {
  const [dismissed, setDismissed] = useState(false);
  if (!status?.sources || dismissed) return null;
  const es = status.sources.eight_sleep;
  const whoop = status.sources.whoop;
  const podBehind = !es || es.days_behind > 2;
  const whoopCovering = whoop && whoop.days_behind <= 2;
  if (!podBehind || whoopCovering) return null;
  return (
    <div className="banner" style={{ display: "flex", justifyContent: "space-between", gap: "1rem" }}>
      <span>
        NO NIGHTLY DATA{es ? ` in ${es.days_behind}d` : ""} — your Eight Sleep pod hasn't reported.
        Check it's online, then:{" "}
        <span className="mono">healthos sync --days 7 --source eight_sleep</span>
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

// Compact "time asleep last night" hero — total duration big, stages as a thin
// bar, source labeled when it's a fallback (pod) rather than Whoop.
function HeroSleep({ sleep }) {
  if (!sleep) {
    return (
      <div className="panel hero">
        <div className="label">Time asleep</div>
        <div className="metric-value xl" style={{ color: "var(--muted)" }}>—</div>
        <div className="metric-sub">no sleep recorded last night</div>
      </div>
    );
  }
  const segs = [
    { cls: "seg-deep", min: sleep.deep_minutes },
    { cls: "seg-rem", min: sleep.rem_minutes },
    { cls: "seg-light", min: sleep.light_minutes },
    { cls: "seg-awake", min: sleep.awake_minutes },
  ];
  const total = segs.reduce((a, s) => a + (s.min || 0), 0) || 1;
  const sub =
    sleep.source !== "whoop"
      ? `via ${sleep.source} (fallback)`
      : sleep.sleep_score
        ? `whoop · score ${num(sleep.sleep_score)}`
        : "whoop";
  return (
    <div className="panel hero">
      <div className="label">Time asleep</div>
      <div className="metric-value xl">{hm(sleep.total_minutes)}</div>
      <div className="metric-sub">{sub}</div>
      <div className="hero-trend">
        {segs.some((s) => s.min) && (
          <div className="sleepbar" style={{ margin: 0 }}>
            {segs.map((s) => (
              <span key={s.cls} className={s.cls} style={{ width: `${((s.min || 0) / total) * 100}%` }} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// The day's context from the input side: your latest logged food / meds /
// supplements, so cause sits next to effect on the Pulse page.
function RecentIntake({ entries }) {
  const recent = (entries || []).slice(0, 4);
  return (
    <div className="grid" style={{ marginTop: "0.85rem" }}>
      <div className="panel">
        <div className="label">Recent intake</div>
        {entries == null ? (
          <div className="metric-sub" style={{ marginTop: "0.35rem" }}>loading…</div>
        ) : recent.length === 0 ? (
          <div className="metric-sub" style={{ marginTop: "0.35rem" }}>
            nothing logged recently — add it on the Journal tab.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.45rem", marginTop: "0.45rem" }}>
            {recent.map((e) => (
              <div
                key={e.id}
                style={{ display: "flex", justifyContent: "space-between", gap: "0.7rem", alignItems: "center", flexWrap: "wrap" }}
              >
                <span className="mono" style={{ fontSize: "0.8rem" }}>
                  <span className="muted" style={{ fontSize: "0.68rem", marginRight: "0.5rem" }}>{e.date}</span>
                  {e.text}
                </span>
                <span style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap" }}>
                  {(e.tags || []).map((t) => (
                    <span
                      key={t}
                      className="mono"
                      style={{ fontSize: "0.62rem", background: "#16302e", color: "#2dd4bf", borderRadius: 4, padding: "1px 5px" }}
                    >
                      {t}
                    </span>
                  ))}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// The inflammation-linked vitals summarized against your own baseline.
// Descriptive, not diagnostic: elevated respiratory rate / skin temp / resting
// HR with suppressed HRV is the wearable pattern worth watching during a flare.
const INFLAMMATION_MARKERS = [
  { key: "respiratory_rate", label: "resp rate", bad: "up", thresh: 5 },
  { key: "skin_temp", label: "skin temp", bad: "up", thresh: 1.5 },
  { key: "resting_hr", label: "resting HR", bad: "up", thresh: 5 },
  { key: "hrv_rmssd", label: "HRV", bad: "down", thresh: 7 },
  { key: "spo2", label: "SpO₂", bad: "down", thresh: 2 },
];

// Why a marker can't be judged: no value synced, a value that came from a
// fallback/estimated source (delta suppressed), or a value with no baseline to
// compare against yet. Kept in sync with the delta rules in api/metrics.py.
const REASON_TEXT = {
  "no reading": "not synced",
  baseline: "building baseline",
  fallback: "fallback source",
  estimated: "estimated",
};

function InflammationRead({ m, buildingBaseline }) {
  const evald = INFLAMMATION_MARKERS.map((mk) => {
    const metric = m[mk.key];
    const value = metric?.value;
    const d = metric?.delta_pct;
    if (value == null) return { ...mk, status: "na", reason: "no reading", value: null, d: null };
    if (d == null) {
      const reason = metric.is_fallback ? "fallback" : metric.is_estimated ? "estimated" : "baseline";
      return { ...mk, status: "na", reason, value, d: null };
    }
    const elevated = mk.bad === "up" ? d >= mk.thresh : d <= -mk.thresh;
    return { ...mk, status: elevated ? "elevated" : "ok", value, d };
  });
  const avail = evald.filter((x) => x.status !== "na");
  const flagged = avail.filter((x) => x.status === "elevated");
  const na = evald.filter((x) => x.status === "na");
  const n = flagged.length;
  const color =
    avail.length === 0 ? "var(--muted)" : n === 0 ? "var(--good)" : n <= 1 ? "var(--warn)" : "var(--bad)";

  // When nothing can be judged, say why rather than a bare "no data".
  const readings = na.filter((x) => x.value != null);
  const emptyMsg =
    readings.length === 0
      ? "no vitals synced for this day"
      : buildingBaseline || readings.some((x) => x.reason === "baseline")
        ? `${readings.length} reading${readings.length > 1 ? "s" : ""} in — building baseline to compare`
        : readings.some((x) => x.reason === "fallback")
          ? "on a fallback source — no baseline to compare against"
          : "not enough baseline yet";

  // Compact "waiting on X (why)" line, grouped by reason, so a blank OR partial
  // read explains which markers are missing and what they need.
  const byReason = na.reduce((acc, x) => {
    (acc[x.reason] = acc[x.reason] || []).push(x.label);
    return acc;
  }, {});
  const waiting = Object.entries(byReason)
    .map(([reason, labels]) => `${labels.join(", ")} (${REASON_TEXT[reason] || reason})`)
    .join(" · ");

  return (
    <div className="panel">
      <div className="label">Inflammation markers</div>
      <div className="metric-value xl" style={{ color }}>
        {avail.length === 0 ? "—" : n}
        {avail.length > 0 && <span className="unit">/ {avail.length} elevated</span>}
      </div>
      <div className="metric-sub">
        {avail.length === 0
          ? emptyMsg
          : n === 0
            ? "all within your normal range"
            : flagged.map((x) => `${x.label} ${x.d > 0 ? "+" : ""}${Math.round(x.d)}%`).join(" · ")}
      </div>
      {na.length > 0 && (
        <div className="mono" style={{ fontSize: "0.62rem", color: "var(--muted)", marginTop: "0.35rem" }}>
          waiting on {waiting}
        </div>
      )}
    </div>
  );
}

// A headline streak tile (workout / sleep), mirroring the Streak & Sleep tabs.
// The streak is a rolling "current" figure, independent of the viewed day.
function StreakHero({ label, icon, count, longest, unit, loading }) {
  return (
    <div className="panel hero">
      <div className="label">{label}</div>
      <div className="metric-value xl" style={{ color: count > 0 ? "var(--accent)" : "var(--muted)" }}>
        {loading ? "…" : `${icon} ${count}`}
      </div>
      <div className="metric-sub">
        {loading ? "loading…" : count > 0 ? `${unit} kept going · best ${longest}` : `start ${unit === "days" ? "today" : "tonight"}`}
      </div>
    </div>
  );
}

// Uppercase mono section label to group the folded breakdown, matching the
// Streaks page headings.
function SectionHeading({ children }) {
  return (
    <div
      style={{
        fontFamily: "var(--mono)",
        fontSize: "0.74rem",
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        color: "var(--muted)",
        margin: "1.1rem 0 0.6rem",
      }}
    >
      {children}
    </div>
  );
}

export default function DailyView() {
  const [date, setDate] = useState(null); // null = latest complete day (Pulse default)
  const [showAll, setShowAll] = useState(false);
  const { data: daily, loading, error } = useHealthData(() => api.daily(date), [date]);
  const { data: hrvTrend } = useHealthData(() => api.trend("hrv_rmssd", 30, 7), []);
  const { data: rhrTrend } = useHealthData(() => api.trend("resting_hr", 30, 7), []);
  const { data: status } = useHealthData(() => api.status(), []);
  const { data: journal } = useHealthData(() => api.journal(7), []);
  // Streak headliners: same inputs the Streak/Sleep tabs use, so the numbers agree.
  const { data: stepsTrend } = useHealthData(() => api.trend("steps", 90), []);
  const { data: workoutsHist } = useHealthData(() => api.workouts(90), []);
  const { data: sleepHist } = useHealthData(() => api.sleep(90), []);
  const { data: rhrRaw } = useHealthData(() => api.trend("resting_hr", 90, 1), []);
  const { data: calendar } = useHealthData(() => api.calendar(90), []);
  const [goal] = useStepGoal();
  const [skipDays] = useSkipDays();
  const [rhrOffset] = useRhrOffset();

  const act = activityStreak(stepsTrend?.series, workoutsHist, goal, skipDays);
  const slp = sleepStreak({ sleep: sleepHist, rhrSeries: rhrRaw?.series, calendar, rhrOffset });

  const today = todayISO();
  const atToday = daily && daily.date >= today;

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

  // Note: Pulse defaults to the latest complete day server-side (a null date
  // fetches it). When you deliberately navigate to an empty day we now SHOW the
  // "no data" panel (with a "view latest complete day" button) rather than
  // silently yanking you back — so an empty day can actually be inspected.

  if (!daily && loading) return <div className="muted mono">loading…</div>;
  if (error) return <div className="error">error: {error}</div>;
  if (!daily) return null;

  const m = daily.metrics;
  const hasData = Object.values(m).some((x) => x && x.value != null) || daily.sleep != null;
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
        <button onClick={() => setDate(shiftDate(daily.date, -1))} aria-label="previous day">‹</button>
        <DatePicker value={daily.date} onChange={(d) => setDate(d)} max={today} />
        <button
          onClick={() => setDate(shiftDate(daily.date, 1))}
          aria-label="next day"
          disabled={atToday}
          style={atToday ? { opacity: 0.3, cursor: "default" } : undefined}
        >›</button>
        <button className="ghost" onClick={() => setDate(today)} disabled={daily.date === today}>today</button>
        <button className="ghost" onClick={() => setDate(null)} disabled={date === null}>latest</button>
        {date === null && <span className="muted mono" style={{ fontSize: "0.7rem" }}>· latest complete day</span>}
        <span className="muted mono" style={{ fontSize: "0.7rem", marginLeft: "0.5rem" }}>← → t</span>
      </div>

      <div style={loading ? { opacity: 0.45, pointerEvents: "none" } : undefined}>
        {!hasData ? (
          <div className="panel" style={{ textAlign: "center", padding: "2.2rem 1rem" }}>
            <div className="metric-value" style={{ color: "var(--muted)" }}>No data for {daily.date}</div>
            <div className="metric-sub" style={{ marginTop: "0.45rem" }}>
              {daily.date >= today
                ? "today's metrics sync after your night + the morning recovery upload"
                : "nothing was recorded for this day"}
            </div>
            {date !== null && (
              <button className="ghost" style={{ marginTop: "0.9rem" }} onClick={() => setDate(null)}>
                view latest complete day
              </button>
            )}
          </div>
        ) : (
        <>
        {/* Four headline signals: cardiac readiness + the two streaks. Every
            other metric folds into the breakdown below. */}
        <div className="grid cols-4">
          <HeroMetric
            label="HRV (nocturnal)"
            metric={m.hrv_rmssd}
            unit="ms"
            trend={trendUpTo(hrvTrend, daily.date)}
            color="#f59e0b"
          />
          <HeroMetric
            label="Resting HR"
            metric={m.resting_hr}
            unit="bpm"
            trend={trendUpTo(rhrTrend, daily.date)}
            color="#38bdf8"
          />
          <StreakHero
            label="Workout streak"
            icon="🔥"
            count={act.streak}
            longest={act.longest}
            unit="days"
            loading={stepsTrend == null}
          />
          <StreakHero
            label="Sleep streak"
            icon="🌙"
            count={slp.streak}
            longest={slp.longest}
            unit="nights"
            loading={sleepHist == null}
          />
        </div>

        <button className="section-toggle" onClick={() => setShowAll((s) => !s)}>
          {showAll ? "▾ hide full breakdown" : "▸ full breakdown"}
        </button>

        {showAll && (
          <>
            {/* Vitals: the cardiac trend + the inflammation read and its markers. */}
            <SectionHeading>Vitals</SectionHeading>
            <div className="grid cols-2">
              <TrendSnapshot label="HRV trend" trend={hrvTrend} unit="ms" betterWhen="up" color="#f59e0b" />
              <TrendSnapshot label="Resting HR trend" trend={rhrTrend} unit="bpm" betterWhen="down" color="#38bdf8" />
            </div>
            <div className="grid" style={{ marginTop: "0.85rem" }}>
              <InflammationRead m={m} buildingBaseline={daily.building_baseline} />
            </div>
            <div className="grid cols-3" style={{ marginTop: "0.85rem" }}>
              <MetricStat label="Respiratory rate" metric={m.respiratory_rate} unit="br/min" digits={1} neutral />
              <MetricStat label="Skin temp" metric={m.skin_temp} unit="°C" digits={1} neutral />
              <MetricStat label="SpO₂" metric={m.spo2} unit="%" neutral />
            </div>

            {/* Sleep: last night's duration + stages + the night's events. */}
            <SectionHeading>Sleep</SectionHeading>
            <div className="grid cols-2">
              <HeroSleep sleep={daily.sleep} />
              <SleepCard sleep={daily.sleep} />
            </div>
            <div className="grid" style={{ marginTop: "0.85rem" }}>
              <EventTimeline events={daily.events} title="Inferred / confirmed events" />
            </div>

            {/* Recovery & activity. */}
            <SectionHeading>Recovery &amp; activity</SectionHeading>
            <div className="grid cols-3">
              <RecoveryScore metric={m.recovery_score} />
              <MetricStat label="Strain" metric={m.strain_score} digits={1} neutral />
              <MetricStat label="Steps" metric={m.steps} neutral />
            </div>
            <div className="grid" style={{ marginTop: "0.85rem" }}>
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

            {/* Day context: what you logged, the attribution, and the calendar. */}
            <SectionHeading>Day context</SectionHeading>
            <RecentIntake entries={journal} />
            <div className="grid" style={{ marginTop: "0.85rem" }}>
              <AttributionPanel date={daily.date} />
            </div>
            <div className="grid" style={{ marginTop: "0.85rem" }}>
              <CalendarStrip events={daily.calendar} viewDate={daily.date} />
            </div>
          </>
        )}
        </>
        )}
      </div>
    </>
  );
}
