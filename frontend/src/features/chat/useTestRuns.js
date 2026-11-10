import { useCallback, useEffect, useState } from "react";
import { json, request } from "../../api.js";

// Test cases of the deployed API and the result of the last run. Refetched when the backend announces `ai.testrun` (anyone ran the tests).
export function useTestRuns({ diagramId, subscribe }) {
  const [data, setData] = useState(null), [running, setRunning] = useState(false), [error, setError] = useState("");
  const load = useCallback(() => request(`/diagrams/${diagramId}/tests`).then((value) => { setData(value); setError(""); }).catch((e) => setError(e.message)), [diagramId]);
  useEffect(() => { setData(null); load(); }, [load]);
  useEffect(() => subscribe((event) => { if (event.event === "ai.testrun") load(); }), [subscribe, load]);
  const run = useCallback(async ({ includeMutating = false, endpoint = null } = {}) => {
    setRunning(true); setError("");
    try { await request(`/diagrams/${diagramId}/tests/run`, json("POST", { include_mutating: includeMutating, endpoint })); }
    catch (e) { setError(e.message); }
    finally { setRunning(false); load(); }
  }, [diagramId, load]);
  const dismissError = useCallback(() => setError(""), []);
  return { data, running, error, run, refresh: load, dismissError };
}
