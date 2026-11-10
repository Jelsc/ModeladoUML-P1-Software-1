// Pure helpers for the changes the AI proposes to the diagram (no React, no DOM). Nothing reaches the canvas until a member accepts.
export const PROPOSAL_STATUS = { pending: "Pendiente", accepted: "Aceptada", rejected: "Rechazada", stale: "Ya no se podía aplicar" };
export const proposalStatusLabel = (status) => PROPOSAL_STATUS[status] || status;

export const pendingProposals = (items) => items.filter((item) => item.status === "pending");

export function proposalSummary(items) {
  const pending = pendingProposals(items).length;
  if (!items.length) return "Sin propuestas de la IA";
  if (!pending) return "Sin propuestas pendientes";
  return `${pending} propuesta${pending === 1 ? "" : "s"} pendiente${pending === 1 ? "" : "s"} de aprobación`;
}

// Pending first (they need a decision, oldest first so the team answers in the order they were asked), then the decided ones, newest first.
export const sortProposals = (items) => [...items].sort((a, b) => (a.status === "pending" ? 0 : 1) - (b.status === "pending" ? 0 : 1)
  || (a.status === "pending" ? String(a.created_at).localeCompare(String(b.created_at)) : String(b.created_at).localeCompare(String(a.created_at))));

export const replaceProposal = (items, updated) => items.some((item) => item.id === updated.id) ? items.map((item) => item.id === updated.id ? updated : item) : [...items, updated];

// One line saying what happened to a decided proposal.
export function decisionNote(item) {
  if (item.status === "pending") return `Pedida por ${item.requested_by || "alguien del equipo"}`;
  const who = item.decided_by ? ` por ${item.decided_by}` : "";
  if (item.status === "accepted") return `Aceptada${who}`;
  if (item.status === "rejected") return `Rechazada${who}`;
  return `Ya no se podía aplicar${who}: el diagrama cambió`;
}
