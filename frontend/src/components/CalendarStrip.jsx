// Calendar context for the day + the night before — the "why" behind a dip.
// Evening events and alcohol/travel-tagged events are highlighted.
function tagIcon(keywords) {
  if (keywords?.includes("alcohol")) return "🍷";
  if (keywords?.includes("travel")) return "✈️";
  return "";
}

export default function CalendarStrip({ events }) {
  if (!events || events.length === 0) {
    return (
      <div className="panel">
        <div className="label">Calendar context</div>
        <div className="metric-sub">No events (add a secret .ics URL to enable).</div>
      </div>
    );
  }
  return (
    <div className="panel">
      <div className="label">Calendar context</div>
      <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
        {events.map((e, i) => (
          <div
            key={`${e.title}-${i}`}
            className="mono"
            style={{ fontSize: "0.78rem", display: "flex", gap: "0.5rem", alignItems: "baseline" }}
          >
            <span className="muted" style={{ minWidth: "3.2rem" }}>
              {e.all_day ? "all-day" : (e.start_time || "").slice(11, 16)}
            </span>
            <span style={{ color: e.is_evening ? "var(--accent)" : "var(--text)" }}>
              {tagIcon(e.keywords)} {e.title || "(untitled)"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
