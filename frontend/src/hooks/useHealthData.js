import { useEffect, useState } from "react";

// A tiny global refresh bus: every mounted useHealthData subscribes, so a single
// triggerGlobalRefresh() re-runs every fetcher in place — refreshing all data
// WITHOUT a full page reload (which would wipe in-progress form state).
const refreshListeners = new Set();
export function triggerGlobalRefresh() {
  for (const fn of refreshListeners) fn();
}

// Generic data hook: runs an api fetcher and tracks loading/error/data. The
// fetcher is keyed by `deps` so views can refetch when their controls change,
// and it also refetches on a global refresh.
export function useHealthData(fetcher, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshNonce, setRefreshNonce] = useState(0);

  useEffect(() => {
    const bump = () => setRefreshNonce((n) => n + 1);
    refreshListeners.add(bump);
    return () => refreshListeners.delete(bump);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    // Promise.resolve().then(...) so a synchronous throw in the fetcher lands
    // in .catch (an error message) instead of blanking the whole view.
    Promise.resolve()
      .then(() => fetcher())
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, refreshNonce]);

  return { data, error, loading };
}
