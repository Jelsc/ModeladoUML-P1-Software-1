import { useCallback, useEffect, useState } from "react";
import { json, request } from "../../api.js";

// Per-diagram AI switches. Everyone can read them; only the owner can change them (the backend enforces it).
export function useAiSettings({ diagramId, subscribe }) {
  const [settings, setSettings] = useState({ ai_enabled: true, ai_can_edit: true, ai_requires_approval: true }), [saving, setSaving] = useState(false), [error, setError] = useState("");
  useEffect(() => { let alive = true; request(`/diagrams/${diagramId}/ai-settings`).then((value) => { if (alive) setSettings(value); }).catch(() => {}); return () => { alive = false; }; }, [diagramId]);
  useEffect(() => subscribe((event) => { if (event.event === "ai.settings") setSettings({ ai_enabled: !!event.ai_enabled, ai_can_edit: !!event.ai_can_edit, ai_requires_approval: event.ai_requires_approval !== false }); }), [subscribe]);
  const update = useCallback(async (patch) => {
    setSaving(true); setError("");
    try { setSettings(await request(`/diagrams/${diagramId}/ai-settings`, json("PUT", { ...settings, ...patch }))); }
    catch (e) { setError(e.message); }
    finally { setSaving(false); }
  }, [diagramId, settings]);
  return { settings, saving, error, update };
}
