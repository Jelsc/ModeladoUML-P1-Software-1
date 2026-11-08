// Pure chat helpers: no React and no DOM, so Node check scripts can import them.
export const CHAT_PAGE_SIZE = 50;
export const CHAT_MAX_LENGTH = 2000;

// Every diagram has exactly three fixed team chats served by the same AI (ids match the backend). Only "diseno" lets the AI edit the diagram.
export const CHANNELS = [
  { id: "diseno", label: "Diseño", hint: "Cambios y decisiones del diagrama", placeholder: "Pida un cambio o escriba al equipo (@ia para hablar con la IA)", aiEdits: true },
  { id: "desarrollo", label: "Desarrollo", hint: "Flujo de métodos y endpoints del backend generado", placeholder: "Pregunte por el backend generado (@ia para hablar con la IA)", aiEdits: false },
  { id: "test", label: "Test", hint: "Casos de prueba y verificaciones", placeholder: "Plantee pruebas (@ia para hablar con la IA)", aiEdits: false },
];
export const DEFAULT_CHANNEL = "diseno";
export const channelOf = (id) => CHANNELS.find((channel) => channel.id === id) || CHANNELS[0];
export const messageChannel = (message) => channelOf(message?.channel).id;
export const emptyChats = () => Object.fromEntries(CHANNELS.map((channel) => [channel.id, { messages: [], loading: true, hasMore: false }]));
export const emptyUnread = () => Object.fromEntries(CHANNELS.map((channel) => [channel.id, 0]));
export const bumpUnread = (unread, channel) => ({ ...unread, [channel]: (unread[channel] || 0) + 1 });
export const clearUnread = (unread, channel) => unread[channel] ? { ...unread, [channel]: 0 } : unread;
export const totalUnread = (unread) => Object.values(unread).reduce((sum, count) => sum + count, 0);

const timeOf = (message) => Date.parse(message.created_at) || 0;

// Idempotent merge: the same message can arrive from the POST response and from the realtime event.
export function mergeMessages(current, incoming) {
  const byId = new Map(current.map((message) => [message.id, message]));
  for (const message of incoming || []) if (message && message.id) byId.set(message.id, { ...byId.get(message.id), ...message });
  return [...byId.values()].sort((a, b) => timeOf(a) - timeOf(b) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
}

export const oldestCreatedAt = (messages) => messages.length ? messages[0].created_at : null;

export const isOwnMessage = (message, userId) => message.author_kind === "user" && message.author_user_id != null && String(message.author_user_id) === String(userId);

export const authorLabel = (message) => message.author_kind === "ai" ? "IA" : message.author_kind === "system" ? "Sistema" : message.author_name || "Usuario eliminado";

export const canSend = (draft) => { const length = draft.trim().length; return length > 0 && length <= CHAT_MAX_LENGTH; };

export function clipText(value, max) {
  const flat = String(value ?? "").replace(/\s+/g, " ").trim();
  return flat.length <= max ? flat : `${flat.slice(0, max - 1)}…`;
}

export function replyPreview(message, messages) {
  if (!message.reply_to_id) return null;
  const target = messages.find((item) => item.id === message.reply_to_id);
  return target ? { author: authorLabel(target), text: clipText(target.content, 90) } : { author: "Mensaje", text: "no disponible en el historial cargado" };
}

const two = (value) => String(value).padStart(2, "0");
export function formatChatTime(iso, now = new Date()) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const clock = `${two(date.getHours())}:${two(date.getMinutes())}`;
  return date.toDateString() === now.toDateString() ? clock : `${two(date.getDate())}/${two(date.getMonth() + 1)} ${clock}`;
}

// "La IA está respondiendo..." bookkeeping. ai.thinking carries the id of the question; ai.done carries it as trigger_id.
export const THINKING_TTL_MS = 90000;
export const addThinking = (list, event) => list.some((item) => item.messageId === event.message_id) ? list : [...list, { messageId: event.message_id, requester: event.requester || "alguien", channel: event.channel || DEFAULT_CHANNEL }];
export const removeThinking = (list, messageId) => list.filter((item) => item.messageId !== messageId);
export function thinkingLabel(all, channel) {
  const list = channel ? all.filter((item) => item.channel === channel) : all;
  if (!list.length) return "";
  const names = [...new Set(list.map((item) => item.requester))];
  const who = names.length === 1 ? names[0] : names.length === 2 ? `${names[0]} y ${names[1]}` : `${names[0]} y ${names.length - 1} más`;
  return `La IA está respondiendo a ${who}...`;
}

// The AI composes "Hecho:" / "No hice:" bullet lists after its text; render them as lists instead of raw text.
export function parseAiMessage(content) {
  return String(content ?? "").split(/\n{2,}/).map((block) => {
    const lines = block.split("\n"), head = lines[0].trim();
    if ((head === "Hecho:" || head === "No hice:") && lines.length > 1) return { type: "list", title: head.slice(0, -1), tone: head === "Hecho:" ? "done" : "skipped", items: lines.slice(1).map((line) => line.replace(/^\s*[•-]\s*/, "").trim()).filter(Boolean) };
    return { type: "text", text: block };
  }).filter((block) => block.type === "list" || block.text.trim());
}

// "@" autocomplete: only one mention exists (@ia), offered while the last word is "@", "@i" or "@ia".
const MENTION_TAIL = /(^|\s)@(i|ia)?$/i;
export const mentionOpen = (draft) => MENTION_TAIL.test(draft);
export const applyMention = (draft) => draft.replace(MENTION_TAIL, (_, lead) => `${lead}@ia `);
export const AI_HIGHLIGHT_MS = 6000;
