import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";

// Which source filled each (metric, day) cell — gaps and provenance at a glance.
const SOURCE_COLOR = {
  whoop: "#f59e0b",
  garmin: "#4ade80",
  eight_sleep: "#38bdf8",
  apple_health: "#a855f7",
  ios_shortcut: "#a855f7",
  estimated: "#6b7280",
};

const LABELS = {
  recovery_score: "Recovery",
  hrv_rmssd: "HRV",
  resting_hr: "Resting HR",
  strain_score: "Strain",
  sleep_duration_minutes: "Sleep",
  respiratory_rate: "Resp. rate",
  spo2: "SpO₂",
  steps: "Steps",
};

function color(source) {
  return source ? SOURCE_COLOR[source] || "#777" : "#161616";
}

export default function CoverageView() {
  const { data, loading, error } = useHealthData(() => api.coverage(60), []);
  if (loading) return <div className="muted mono">loading…</div>;
  if (error) return <div className="error">error: {error}</div>;

  const { metrics, dates, grid } = data;

  return (
    <>
      <div className="statusline" style={{ marginBottom: "0.8rem" }}>
        data coverage · last {dates.length} days · who filled each cell
      </div>
      <div className="panel" style={{ overflowX: "auto" }}>
        {metrics.map((metric) => (
          <div className="cov-row" key={metric}>
            <span className="cov-label">{LABELS[metric] || metric}</span>
            <div className="cov-cells">
              {dates.map((date) => (
                <span
                  key={date}
                  className="cov-cell"
                  style={{ background: color(grid[date][metric]) }}
                  title={`${date} · ${grid[date][metric] || "no data"}`}
                />
              ))}
            </div>
          </div>
        ))}
        <div className="legend" style={{ marginTop: "0.8rem" }}>
          {Object.entries(SOURCE_COLOR).map(([src, c]) =>
            src === "ios_shortcut" ? null : (
              <span key={src}>
                <i style={{ background: c }} />
                {src}
              </span>
            )
          )}
          <span>
            <i style={{ background: "#161616" }} />
            missing
          </span>
        </div>
      </div>
    </>
  );
}
