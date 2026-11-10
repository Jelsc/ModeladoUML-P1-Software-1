import { useCallback, useEffect, useState } from "react";
import { request } from "../../api.js";

// Changes the AI proposed to the diagram. The list is refetched when the backend announces `ai.proposals` (proposed, accepted, rejected by anyone).
export function useProposals({ diagramId, subscribe }) {
  const [items, setItems] = useState([]), [error, setError] = useState(""), [busyId, setBusyId] = useState(null);
  const load = useCallback(() => request(`/diagrams/${diagramId}/ai-proposals`).then((list) => { setItems(list); setError(""); }).catch((e) => setError(e.message)), [diagramId]);
  useEffect(() => { setItems([]); load(); }, [load]);
  useEffect(() => subscribe((event) => { if (event.event === "ai.proposals") load(); }), [subscribe, load]);
  const decide = useCallback(async (id, verb) => {
    setBusyId(id); setError("");
    try { await request(`/ai-proposals/${id}/${verb}`, { method: "POST" }); }
    catch (e) { setError(e.message); }  // e.g. someone else already decided: the reload below shows the real state
    finally { setBusyId(null); load(); }
  }, [load]);
  const dismissError = useCallback(() => setError(""), []);
  return { items, error, busyId, accept: (id) => decide(id, "accept"), reject: (id) => decide(id, "reject"), dismissError };
}
