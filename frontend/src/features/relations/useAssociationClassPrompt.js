import { useCallback, useRef, useState } from "react";
import { request } from "../../api.js";
import { isManyToMany, touchesMultiplicity } from "./association-class.js";

export function useAssociationClassPrompt({ mutate, setError }) {
  const [prompt, setPrompt] = useState(null), [busy, setBusy] = useState(false), kept = useRef(new Set()), converting = useRef(false);
  // Only user edits reach this; realtime refreshes never call it, so remote syncs cannot reopen the modal.
  const inspect = useCallback((relationId, patch, diagram) => {
    const relation = diagram?.relations.find((item) => item.id === relationId);
    if (!relation || relation.association_class_id || !touchesMultiplicity(patch)) return;
    if (!isManyToMany(relation)) { kept.current.delete(relationId); return; }
    if (kept.current.has(relationId)) return;
    const name = (classId) => diagram.classes.find((item) => item.id === classId)?.name || "";
    setPrompt({ relationId, source: name(relation.source_id), target: name(relation.target_id) });
  }, []);
  const keep = useCallback(() => { setPrompt((current) => { if (current) kept.current.add(current.relationId); return null; }); }, []);
  const convert = useCallback(async () => {
    if (!prompt || converting.current) return;
    converting.current = true; setBusy(true);
    try { await mutate(() => request(`/relations/${prompt.relationId}/association-class`, { method: "POST" })); kept.current.delete(prompt.relationId); }
    catch (e) { setError(e.message); }
    finally { converting.current = false; setBusy(false); setPrompt(null); }
  }, [mutate, prompt, setError]);
  return { prompt, busy, inspect, keep, convert };
}
