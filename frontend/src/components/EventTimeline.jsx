import { eventMeta } from "../format.js";

// Behavioral event badges. Inferred events render dashed/muted to signal lower
// confidence vs. confirmed/manual ones.
export default function EventTimeline({ events, title = "Events" }) {
  return (
    <div className="panel">
      <div className="label">{title}</div>
      {(!events || events.length === 0) && <div className="metric-sub">None detected.</div>}
      <div className="badges">
        {events?.map((e, i) => {
          const meta = eventMeta(e.event_type);
          return (
            <span
              key={`${e.event_type}-${i}`}
              className={`badge ${e.confidence === "inferred" ? "inferred" : ""}`}
              title={e.notes || ""}
            >
              {meta.icon} {meta.label}
              {e.value != null ? ` ${e.value}` : ""}
            </span>
          );
        })}
      </div>
    </div>
  );
}
