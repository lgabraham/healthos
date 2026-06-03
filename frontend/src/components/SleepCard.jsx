import { hm, num } from "../format.js";

// Sleep as horizontal stacked segments (deep / rem / light / awake).
export default function SleepCard({ sleep }) {
  if (!sleep) {
    return (
      <div className="panel">
        <div className="label">Sleep</div>
        <div className="metric-sub">No canonical sleep session.</div>
      </div>
    );
  }
  const segs = [
    { key: "deep", cls: "seg-deep", min: sleep.deep_minutes },
    { key: "rem", cls: "seg-rem", min: sleep.rem_minutes },
    { key: "light", cls: "seg-light", min: sleep.light_minutes },
    { key: "awake", cls: "seg-awake", min: sleep.awake_minutes },
  ];
  const total = segs.reduce((a, s) => a + (s.min || 0), 0) || 1;

  return (
    <div className="panel">
      <div className="label">Sleep</div>
      <div className="metric-value">
        {hm(sleep.total_minutes)}
        {sleep.sleep_score != null && <span className="unit">score {num(sleep.sleep_score)}</span>}
      </div>
      <div className="sleepbar">
        {segs.map((s) => (
          <span
            key={s.key}
            className={s.cls}
            style={{ width: `${((s.min || 0) / total) * 100}%` }}
            title={`${s.key}: ${hm(s.min)}`}
          />
        ))}
      </div>
      <div className="legend">
        <span><i className="seg-deep" />deep {hm(sleep.deep_minutes)}</span>
        <span><i className="seg-rem" />rem {hm(sleep.rem_minutes)}</span>
        <span><i className="seg-light" />light {hm(sleep.light_minutes)}</span>
        <span><i className="seg-awake" />awake {hm(sleep.awake_minutes)}</span>
      </div>
    </div>
  );
}
