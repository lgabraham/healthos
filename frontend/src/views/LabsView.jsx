import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";
import { sparkPath } from "../components/Sparkline.jsx";

const STATUS_COLOR = {
  in: "var(--good)",
  low: "var(--bad)",
  high: "var(--bad)",
  unknown: "var(--muted)",
};
const STATUS_LABEL = { low: "LOW", high: "HIGH" };

// A tiny sparkline across draws, with the most-recent point dotted in its
// status color. Skips non-numeric markers (e.g. APOE genotype).
function LabSpark({ history, status }) {
  const values = history.map((h) => h.value_num);
  const nums = values.filter((v) => v != null);
  if (nums.length < 2) return <span className="lab-spark-empty" />;
  const W = 96;
  const H = 26;
  const d = sparkPath(values, W, H);
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const span = max - min || 1;
  const lastX = W;
  const lastY = H - ((nums[nums.length - 1] - min) / span) * (H - 2) - 1;
  return (
    <svg className="lab-spark" width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden="true">
      <path d={d} fill="none" stroke="var(--muted)" strokeWidth="1.5" />
      <circle cx={lastX.toFixed(1)} cy={lastY.toFixed(1)} r="2.6" fill={STATUS_COLOR[status]} />
    </svg>
  );
}

function LabRow({ m }) {
  const { latest, trend } = m;
  const color = STATUS_COLOR[latest.status] || "var(--muted)";
  const arrow = trend === "up" ? "↑" : trend === "down" ? "↓" : trend === "flat" ? "→" : "";
  return (
    <div className="lab-row">
      <div className="lab-name">
        {m.marker}
        {m.unit ? <span className="lab-unit"> {m.unit}</span> : null}
      </div>
      <LabSpark history={m.history} status={latest.status} />
      <div className="lab-value" style={{ color }}>
        {latest.value_text}
        {arrow ? <span className="lab-arrow"> {arrow}</span> : null}
      </div>
      <div className="lab-opt">
        {STATUS_LABEL[latest.status] ? (
          <span className="lab-flag" style={{ color }}>
            {STATUS_LABEL[latest.status]}
          </span>
        ) : null}
        {m.optimal_text ? <span className="metric-sub">opt {m.optimal_text}</span> : null}
      </div>
    </div>
  );
}

export default function LabsView() {
  const { data, loading, error } = useHealthData(() => api.labs(), []);
  if (loading) return <div className="muted mono">loading…</div>;
  if (error) return <div className="error">error: {error}</div>;
  if (!data || !data.categories?.length) {
    return (
      <div className="muted mono">
        No lab results yet. Import a panel with <code>healthos labs-import &lt;file&gt;</code>.
      </div>
    );
  }

  const dates = data.draw_dates;
  return (
    <>
      <div className="statusline" style={{ marginBottom: "0.8rem" }}>
        {data.marker_count} markers · {dates.length} draws · {dates[0]} → {dates[dates.length - 1]}
      </div>

      {data.flagged.length > 0 && (
        <div className="panel" style={{ marginBottom: "1rem" }}>
          <div className="label">Out of optimal range ({data.flagged.length})</div>
          <div className="lab-flags">
            {data.flagged.map((f) => (
              <span key={`${f.category}-${f.marker}`} className="lab-flag-chip">
                <b>{f.marker}</b> {f.value_text}
                {f.unit ? ` ${f.unit}` : ""}{" "}
                <span style={{ color: STATUS_COLOR[f.status] }}>{STATUS_LABEL[f.status]}</span>
                <span className="metric-sub"> · opt {f.optimal_text}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {data.categories.map((c) => (
        <div key={c.name} className="panel" style={{ marginBottom: "0.85rem" }}>
          <div className="label">{c.name}</div>
          {c.markers.map((m) => (
            <LabRow key={m.marker} m={m} />
          ))}
        </div>
      ))}
    </>
  );
}
