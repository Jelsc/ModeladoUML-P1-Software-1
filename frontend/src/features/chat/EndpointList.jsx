import { endpointSummary, kindLabel, sortEndpoints, statusLabel } from "./endpoint-model.js";

// Endpoints the AI proposed in the Desarrollo chat. Only the approved ones are generated and deployed with the CRUD.
export function EndpointList({ items, canEdit, busyId, error, onApprove, onUnapprove, onRemove, onDismissError }) {
  const pending = items.some((item) => item.status === "proposed");
  return <details className="board-endpoints" open={pending || undefined}>
    <summary>{endpointSummary(items)}</summary>
    {items.length === 0 && <p className="board-endpoints-empty">Pídale a la IA, por ejemplo: «@ia necesito buscar clientes por email». Los endpoints propuestos aparecen aquí para su aprobación.</p>}
    <ul>{sortEndpoints(items).map((item) => <li key={item.id} className={`board-endpoint ${item.status}`}>
      <div className="board-endpoint-head"><span className={`board-endpoint-method ${item.http_method.toLowerCase()}`}>{item.http_method}</span><code title={item.route}>{item.route}</code></div>
      <div className="board-endpoint-meta"><b>{item.class_name}.{item.name}</b><span>{kindLabel(item.kind)}{item.has_custom_code ? " (Java de la IA)" : ""}</span><span className={`board-endpoint-status ${item.status}`}>{statusLabel(item.status)}</span></div>
      {item.description && <p className="board-endpoint-description">{item.description}</p>}
      {canEdit && <div className="board-endpoint-actions">
        {item.status === "proposed" ? <button type="button" disabled={busyId === item.id} onClick={() => onApprove(item.id)}>Aprobar</button> : <button type="button" className="ghost" disabled={busyId === item.id} onClick={() => onUnapprove(item.id)}>Quitar aprobación</button>}
        <button type="button" className="ghost" disabled={busyId === item.id} onClick={() => onRemove(item.id)} aria-label={`Eliminar el endpoint ${item.name}`}>Eliminar</button>
      </div>}
    </li>)}</ul>
    {error && <p className="error board-chat-error" role="alert">{error} <button type="button" className="ghost" onClick={onDismissError}>Ocultar</button></p>}
  </details>;
}
