// Load data for a page: { data, error, loading, reload }. Optional polling keeps queues and statuses fresh.
//
// LEARNING NOTE: the `alive` flag drops responses that arrive after the component unmounted or the path
// changed; without it, a slow response for case 3 can overwrite the page you've since opened for case 4.
import { useCallback, useEffect, useState } from "react";
import { get } from "./api";

export function useApi<T>(path: string | null, pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!path) return;
    let alive = true;
    get<T>(path)
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e) => alive && setError(e))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [path, tick]);

  useEffect(() => {
    if (!pollMs) return;
    const id = setInterval(reload, pollMs);
    return () => clearInterval(id);
  }, [pollMs, reload]);

  return { data, error, loading, reload };
}
