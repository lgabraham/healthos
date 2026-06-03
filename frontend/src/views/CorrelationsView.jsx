import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";
import CorrelationCard from "../components/CorrelationCard.jsx";

export default function CorrelationsView() {
  const { data, loading, error } = useHealthData(() => api.correlations(90), []);
  if (loading) return <div className="muted mono">loading…</div>;
  if (error) return <div className="error">error: {error}</div>;

  return (
    <>
      <div className="statusline" style={{ marginBottom: "0.8rem" }}>
        90-day window · canonical metrics · sample sizes shown per card
      </div>
      <div className="grid cols-2">
        {data.map((card) => (
          <CorrelationCard key={card.title} card={card} />
        ))}
      </div>
    </>
  );
}
