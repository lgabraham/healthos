import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";
import CorrelationCard from "../components/CorrelationCard.jsx";

const SECTIONS = [
  { group: "behavior", label: "Behaviors → biomarkers", hint: "inferred & logged events" },
  { group: "intake", label: "Journal exposures → biomarkers", hint: "from what you log & tag" },
];

export default function CorrelationsView() {
  const { data, loading, error } = useHealthData(() => api.correlations(90), []);
  if (loading) return <div className="muted mono">loading…</div>;
  if (error) return <div className="error">error: {error}</div>;

  const cards = data || [];
  // Fall back to a single untitled section if older API responses lack `group`.
  const grouped = SECTIONS.map((s) => ({
    ...s,
    cards: cards.filter((c) => (c.group || "behavior") === s.group),
  })).filter((s) => s.cards.length);

  return (
    <>
      <div className="statusline" style={{ marginBottom: "0.8rem" }}>
        90-day window · canonical metrics · sample sizes shown per card
      </div>
      {grouped.map((s) => (
        <div key={s.group} style={{ marginBottom: "1.4rem" }}>
          <div className="label" style={{ marginBottom: "0.6rem" }}>
            {s.label} <span className="metric-sub">· {s.hint}</span>
          </div>
          <div className="grid cols-2">
            {s.cards.map((card) => (
              <CorrelationCard key={card.title} card={card} />
            ))}
          </div>
        </div>
      ))}
      {grouped.length === 0 && (
        <div className="muted mono">No correlations yet — sync data and journal a few entries.</div>
      )}
    </>
  );
}
