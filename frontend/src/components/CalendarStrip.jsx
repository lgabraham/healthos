// Calendar context for the day + the night before — the "why" behind a dip.
// Each event gets a type chip; events from the previous day are labeled, since
// last evening's activity is what shows up in this morning's numbers.
const CAT_COLOR = {
  alcohol: "#f59e0b",
  travel: "#38bdf8",
  work: "#8a8a8a",
  exercise: "#a855f7",
  health: "#ef4444",
  social: "#4ade80",
};

function category(keywords) {
  return keywords && keywords.length ? keywords[0] : null;
}

export default function CalendarStrip({ events, viewDate }) {
  if (!events || events.length === 0) {
    return (
      <div className="panel">
        <div className="label">Calendar context</div>
        <div className="metric-sub">No calendar events for this day or the evening before.</div>
      </div>
    );
  }
  return (
    <div className="panel">
      <div className="label">
        Calendar context <span className="muted">· prev evening shapes this morning's numbers</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
        {events.map((e, i) => {
          const cat = category(e.keywords);
          const isPrev = viewDate && e.date !== viewDate;
          return (
            <div
              key={`${e.title}-${i}`}
              className="mono"
              style={{
                fontSize: "0.78rem",
                display: "flex",
                gap: "0.5rem",
                alignItems: "baseline",
              }}
            >
              <span className="muted" style={{ minWidth: "4.4rem" }}>
                {isPrev ? "prev day" : e.all_day ? "all-day" : (e.start_time || "").slice(11, 16)}
              </span>
              {cat && (
                <span
                  style={{
                    color: CAT_COLOR[cat] || "var(--muted)",
                    border: `1px solid ${CAT_COLOR[cat] || "var(--border)"}`,
                    borderRadius: "2px",
                    padding: "0 0.3rem",
                    fontSize: "0.68rem",
                  }}
                >
                  {cat}
                </span>
              )}
              <span style={{ color: e.is_evening ? "var(--accent)" : "var(--text)", opacity: isPrev ? 0.75 : 1 }}>
                {e.title || "(untitled)"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
