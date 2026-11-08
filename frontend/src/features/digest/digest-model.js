// Pure helpers for the "since your last visit" card: no React, no DOM.
export const DIGEST_VISIBLE_ITEMS = 6;

// Anything worth showing? (first visits and quiet diagrams show nothing)
export const hasDigest = (digest) => !!digest && !!digest.since && (digest.activity_total > 0 || digest.chat_total > 0);

export function formatAway(since, now = new Date()) {
  const minutes = Math.floor((now.getTime() - new Date(since).getTime()) / 60000);
  if (!Number.isFinite(minutes) || minutes < 0) return "";
  if (minutes < 1) return "hace un momento";
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `hace ${hours} h`;
  const days = Math.floor(hours / 24);
  return `hace ${days} ${days === 1 ? "día" : "días"}`;
}

const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;

export function digestHeadline(digest) {
  const parts = [];
  if (digest.activity_total > 0) parts.push(plural(digest.activity_total, "cambio", "cambios"));
  if (digest.chat_total > 0) parts.push(plural(digest.chat_total, "mensaje", "mensajes"));
  return parts.join(" y ");
}

export const digestActors = (digest) => Object.entries(digest.by_actor || {}).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([name, count]) => `${name} (${count})`).join(", ");

// The API returns oldest first; show the newest ones and say how many are hidden.
export function visibleItems(digest, max = DIGEST_VISIBLE_ITEMS) {
  const items = digest.activity || [];
  const shown = items.slice(-max);
  return { shown, hidden: Math.max(0, digest.activity_total - shown.length) };
}

export const SUMMARY_REQUEST = "@ia resumí lo que pasó desde mi última visita";
