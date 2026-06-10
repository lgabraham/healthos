// Thin fetch wrapper. Uses relative URLs so the same build works in dev (Vite
// proxy) and prod (served behind the FastAPI app or a reverse proxy).
const BASE = import.meta.env.VITE_API_BASE || "";

async function get(path) {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    throw new Error(`${path} -> ${res.status}`);
  }
  return res.json();
}

export const api = {
  status: () => get("/api/status"),
  daily: (date) => get(`/api/daily${date ? `?date=${date}` : ""}`),
  trend: (metric, days, rolling = 7) =>
    get(`/api/trend/${metric}?days=${days}&rolling=${rolling}`),
  sleep: (days) => get(`/api/sleep?days=${days}`),
  workouts: (days) => get(`/api/workouts?days=${days}`),
  events: (days, type) =>
    get(`/api/events?days=${days}${type ? `&event_type=${type}` : ""}`),
  correlations: (days) => get(`/api/correlations?days=${days}`),
  coverage: (days) => get(`/api/coverage?days=${days}`),
  syncLog: () => get("/api/sync-log"),
};
