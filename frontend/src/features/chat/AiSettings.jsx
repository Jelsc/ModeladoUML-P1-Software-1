// Status line for everyone; switches for the diagram owner.
export function AiSettings({ settings, canManage, saving, error, onChange }) {
  const status = !settings.ai_enabled ? "La IA está desactivada en este diagrama." : !settings.ai_can_edit ? "La IA responde, pero no puede editar el diagrama." : "";
  if (!canManage) return status ? <p className="board-chat-ai-status" role="status">{status}</p> : null;
  return <details className="board-chat-ai-settings">
    <summary>Ajustes de la IA{status && <span className="board-chat-ai-flag"> · limitada</span>}</summary>
    <label><input type="checkbox" checked={settings.ai_enabled} disabled={saving} onChange={(event) => onChange({ ai_enabled: event.target.checked })} /> IA activa</label>
    <label><input type="checkbox" checked={settings.ai_can_edit} disabled={saving || !settings.ai_enabled} onChange={(event) => onChange({ ai_can_edit: event.target.checked })} /> La IA puede editar el diagrama</label>
    <label><input type="checkbox" checked={settings.ai_requires_approval !== false} disabled={saving || !settings.ai_enabled || !settings.ai_can_edit} onChange={(event) => onChange({ ai_requires_approval: event.target.checked })} /> Los cambios de la IA requieren la aprobación del equipo</label>
    {error && <p className="error" role="alert">{error}</p>}
  </details>;
}
