import { decisionNote, pendingProposals, proposalStatusLabel, proposalSummary, sortProposals } from "./proposal-model.js";

// Changes to the diagram that the AI proposed in Diseño or Desarrollo. They are applied to the canvas only when a member accepts them.
export function ProposalList({ items, canEdit, busyId, error, onAccept, onReject, onDismissError }) {
  const pending = pendingProposals(items).length > 0;
  return <details className="board-proposals" open={pending || undefined}>
    <summary>{proposalSummary(items)}</summary>
    {items.length === 0 && <p className="board-endpoints-empty">Cuando la IA proponga cambios al diagrama aparecerán aquí para que el equipo los acepte o los rechace.</p>}
    <ul>{sortProposals(items).map((item) => <li key={item.id} className={`board-proposal ${item.status}`}>
      <div className="board-proposal-head"><span className={`board-endpoint-status ${item.status}`}>{proposalStatusLabel(item.status)}</span><small>{decisionNote(item)}</small></div>
      <ul className="board-proposal-changes">{item.summary.map((line, index) => <li key={index}>{line}</li>)}</ul>
      {item.status === "stale" && item.result?.skipped?.length > 0 && <p className="board-endpoint-description">{item.result.skipped.join(" · ")}</p>}
      {canEdit && item.status === "pending" && <div className="board-endpoint-actions">
        <button type="button" disabled={busyId === item.id} onClick={() => onAccept(item.id)}>Aceptar</button>
        <button type="button" className="ghost" disabled={busyId === item.id} onClick={() => onReject(item.id)}>Rechazar</button>
      </div>}
    </li>)}</ul>
    {error && <p className="error board-chat-error" role="alert">{error} <button type="button" className="ghost" onClick={onDismissError}>Ocultar</button></p>}
  </details>;
}
