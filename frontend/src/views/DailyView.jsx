import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";
import RecoveryScore from "../components/RecoveryScore.jsx";
import MetricStat from "../components/MetricStat.jsx";
import SleepCard from "../components/SleepCard.jsx";
import EventTimeline from "../components/EventTimeline.jsx";
import { hm, num } from "../format.js";

export default function DailyView() {
  const { data: daily, loading, error } = useHealthData(() => api.daily(), []);
  const { data: hrvTrend } = useHealthData(() => api.trend("hrv_rmssd", 30, 7), []);

  if (loading) return <div className="muted mono">loading…</div>;
  if (error) return <div className="error">error: {error}</div>;

  const m = daily.metrics;
  const spark = (hrvTrend?.series || []).map((d) => d.value);
  const wk = daily.last_workout;

  return (
    <>
      {daily.building_baseline && (
        <div className="banner">
          BUILDING BASELINE — fewer than 14 days of data. Inference and baselines are provisional.
        </div>
      )}
      <div className="statusline" style={{ marginBottom: "0.8rem" }}>
        showing {daily.date}
      </div>

      <div className="grid cols-4">
        <RecoveryScore metric={m.recovery_score} />
        <MetricStat label="HRV (nocturnal)" metric={m.hrv_rmssd} unit="ms" spark={spark} />
        <MetricStat label="Resting HR" metric={m.resting_hr} unit="bpm" />
        <MetricStat label="Strain" metric={m.strain_score} digits={1} />
      </div>

      <div className="grid cols-2" style={{ marginTop: "0.85rem" }}>
        <SleepCard sleep={daily.sleep} />
        <EventTimeline events={daily.events} title="Inferred / confirmed events" />
      </div>

      <div className="grid cols-2" style={{ marginTop: "0.85rem" }}>
        <MetricStat label="Steps" metric={m.steps} />
        <div className="panel">
          <div className="label">Last workout</div>
          {wk ? (
            <>
              <div className="metric-value" style={{ fontSize: "1.2rem" }}>
                {wk.sport_type || "workout"}
              </div>
              <div className="metric-sub">
                {hm(wk.duration_minutes)} · avg {num(wk.hr_avg)}bpm · max {num(wk.hr_max)}bpm
                {wk.tss != null ? ` · TSS ${num(wk.tss)}` : ""}
              </div>
            </>
          ) : (
            <div className="metric-sub">No recent workout.</div>
          )}
        </div>
      </div>
    </>
  );
}
