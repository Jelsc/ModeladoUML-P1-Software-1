import { useCallback, useEffect, useState } from "react";
import { json, request } from "../../api.js";
import { removeEndpoint, replaceEndpoint } from "./endpoint-model.js";

// Endpoints designed by the AI. The list is refetched when the backend announces `ai.endpoints` (proposed, approved, deleted by anyone).
export function useEndpoints({ diagramId, subscribe }) {
  const [items, setItems] = useState([]), [error, setError] = useState(""), [busyId, setBusyId] = useState(null);
  const load = useCallback(() => request(`/diagrams/${diagramId}/endpoints`).then((list) => { setItems(list); setError(""); }).catch((e) => setError(e.message)), [diagramId]);
  useEffect(() => { setItems([]); load(); }, [load]);
  useEffect(() => subscribe((event) => { if (event.event === "ai.endpoints") load(); }), [subscribe, load]);
  const setStatus = useCallback(async (id, status) => {
    setBusyId(id); setError("");
    try { const updated = await request(`/endpoints/${id}`, json("PATCH", { status })); setItems((current) => replaceEndpoint(current, updated)); }
    catch (e) { setError(e.message); }
    finally { setBusyId(null); }
  }, []);
  const remove = useCallback(async (id) => {
    setBusyId(id); setError("");
    try { await request(`/endpoints/${id}`, { method: "DELETE" }); setItems((current) => removeEndpoint(current, id)); }
    catch (e) { setError(e.message); }
    finally { setBusyId(null); }
  }, []);
  const dismissError = useCallback(() => setError(""), []);
  return { items, error, busyId, approve: (id) => setStatus(id, "approved"), unapprove: (id) => setStatus(id, "proposed"), remove, dismissError };
}
