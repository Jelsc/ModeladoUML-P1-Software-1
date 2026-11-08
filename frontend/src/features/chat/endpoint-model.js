// Pure helpers for the endpoints the AI designs in the Desarrollo chat (no React, no DOM).
export const ENDPOINT_STATUS = { proposed: "Pendiente", approved: "Aprobado" };
export const KIND_LABELS = { find_by_field: "Buscar por campo", count: "Contar", sum_field: "Sumar campo", set_field: "Cambiar campo", custom: "Código personalizado" };

export const statusLabel = (status) => ENDPOINT_STATUS[status] || status;
export const kindLabel = (kind) => KIND_LABELS[kind] || kind;

// Pending ones first (they need a decision), then by class and name.
export const sortEndpoints = (items) => [...items].sort((a, b) => (a.status === "proposed" ? 0 : 1) - (b.status === "proposed" ? 0 : 1) || String(a.class_name).localeCompare(String(b.class_name)) || String(a.name).localeCompare(String(b.name)));

export function endpointSummary(items) {
  const pending = items.filter((item) => item.status === "proposed").length, approved = items.length - pending;
  if (!items.length) return "Sin endpoints de la IA";
  return `${items.length} endpoint${items.length === 1 ? "" : "s"} · ${approved} aprobado${approved === 1 ? "" : "s"} · ${pending} pendiente${pending === 1 ? "" : "s"}`;
}

export const replaceEndpoint = (items, updated) => items.some((item) => item.id === updated.id) ? items.map((item) => item.id === updated.id ? updated : item) : [...items, updated];
export const removeEndpoint = (items, id) => items.filter((item) => item.id !== id);
