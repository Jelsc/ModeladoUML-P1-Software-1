import { digestActors, digestHeadline, formatAway, visibleItems } from "./digest-model.js";

export function DigestCard({ digest, canAsk, onAskAi, onDismiss }) {
  const { shown, hidden } = visibleItems(digest), actors = digestActors(digest);
  return <section className="board-digest" role="region" aria-label="Novedades desde su última visita">
    <header><h2>Desde tu última visita <small>({formatAway(digest.since)})</small></h2></header>
    <p><b>{digestHeadline(digest)}</b>{actors && <span className="muted"> · {actors}</span>}</p>
    {shown.length > 0 && <ul>{shown.map((item) => <li key={item.id} className={item.actor_kind === "ai" ? "ai" : ""}>{item.summary}</li>)}</ul>}
    {hidden > 0 && <p className="muted">y {hidden} más...</p>}
    <div className="board-digest-actions">
      {canAsk && <button type="button" onClick={onAskAi}>Resumir con la IA</button>}
      <button type="button" className="ghost" onClick={onDismiss}>Entendido</button>
    </div>
  </section>;
}
