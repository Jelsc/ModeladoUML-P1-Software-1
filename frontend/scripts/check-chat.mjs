import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { CHAT_MAX_LENGTH, addThinking, applyMention, authorLabel, canSend, clipText, formatChatTime, isOwnMessage, mentionOpen, mergeMessages, oldestCreatedAt, parseAiMessage, removeThinking, replyPreview, thinkingLabel } from "../src/features/chat/chat-model.js";

const msg = (id, minute, extra = {}) => ({ id, created_at: `2026-01-01T12:${String(minute).padStart(2, "0")}:00+00:00`, content: id, author_kind: "user", author_user_id: 1, author_name: "Ana", ...extra });

// mergeMessages: idempotent (POST response + realtime event), sorted, immutable.
const base = [msg("b", 2), msg("a", 1)];
const merged = mergeMessages(base, [msg("c", 3), msg("a", 1)]);
assert.deepEqual(merged.map((m) => m.id), ["a", "b", "c"]);
assert.deepEqual(mergeMessages(merged, [msg("c", 3)]).map((m) => m.id), ["a", "b", "c"], "same message twice must not duplicate");
assert.deepEqual(base.map((m) => m.id), ["b", "a"], "input must not be mutated");
assert.deepEqual(mergeMessages([], [msg("old", 0), msg("new", 5)]).map((m) => m.id), ["old", "new"]);
assert.deepEqual(mergeMessages([msg("a", 1)], null).map((m) => m.id), ["a"]);
assert.equal(mergeMessages([msg("a", 1)], [{ ...msg("a", 1), content: "edited" }])[0].content, "edited");
// Different UTC offsets are compared as instants, not as strings.
const offset = mergeMessages([], [msg("late", 0, { created_at: "2026-01-01T09:30:00-04:00" }), msg("early", 0, { created_at: "2026-01-01T12:00:00+00:00" })]);
assert.deepEqual(offset.map((m) => m.id), ["early", "late"]);

assert.equal(oldestCreatedAt([]), null);
assert.equal(oldestCreatedAt(merged), merged[0].created_at);

// Identity helpers.
assert.equal(isOwnMessage(msg("a", 1), 1), true);
assert.equal(isOwnMessage(msg("a", 1), "1"), true);
assert.equal(isOwnMessage(msg("a", 1), 2), false);
assert.equal(isOwnMessage(msg("a", 1, { author_kind: "ai", author_user_id: null }), 1), false);
assert.equal(isOwnMessage(msg("a", 1, { author_user_id: null }), 1), false);
assert.equal(authorLabel(msg("a", 1)), "Ana");
assert.equal(authorLabel(msg("a", 1, { author_kind: "ai", author_name: null })), "IA");
assert.equal(authorLabel(msg("a", 1, { author_name: null })), "Usuario eliminado");

// Composer limits mirror the backend (1..2000 after trimming).
assert.equal(canSend(""), false);
assert.equal(canSend("   \n"), false);
assert.equal(canSend("hola"), true);
assert.equal(canSend("a".repeat(CHAT_MAX_LENGTH)), true);
assert.equal(canSend("a".repeat(CHAT_MAX_LENGTH + 1)), false);
assert.equal(canSend(` ${"a".repeat(CHAT_MAX_LENGTH)} `), true, "limit applies to trimmed text, like the backend");

// Reply previews.
assert.equal(clipText("a  b\n c", 50), "a b c");
assert.equal(clipText("x".repeat(100), 10).length, 10);
assert.deepEqual(replyPreview(msg("r", 2, { reply_to_id: "a" }), [msg("a", 1, { content: "pregunta" })]), { author: "Ana", text: "pregunta" });
assert.equal(replyPreview(msg("r", 2), []), null);
assert.equal(replyPreview(msg("r", 2, { reply_to_id: "gone" }), []).author, "Mensaje");

// Time formatting: clock for today, date + clock for other days, empty for garbage.
const now = new Date(2026, 0, 15, 18, 0, 0);
assert.equal(formatChatTime(new Date(2026, 0, 15, 9, 5, 0).toISOString(), now), "09:05");
assert.equal(formatChatTime(new Date(2026, 0, 3, 23, 59, 0).toISOString(), now), "03/01 23:59");
assert.equal(formatChatTime("not-a-date", now), "");

// Wiring: the board must route chat events away from the full-diagram refresh path.
const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const collaboration = read("../src/features/canvas/useCanvasCollaboration.js");
assert.match(collaboration, /\/\^\(chat\|ai\)\\\.\/\.test\(event\.event\)/, "chat/ai events must be dispatched to listeners");
assert.ok(collaboration.indexOf("clientListeners.current.forEach") < collaboration.indexOf("refreshRef.current()"), "chat dispatch must happen before the generic refresh branch");
assert.match(collaboration, /return \{[^}]*subscribe/);
const board = read("../src/pages/board-canvas.jsx");
assert.match(board, /useDiagramChat\(\{[^}]*subscribe: collaboration\.subscribe/);
assert.match(board, /<ChatPanel /);
assert.match(board, /<ChatLauncher /);
assert.doesNotMatch(board.split("\n").filter((line) => /assistant-overlay/.test(line)).join("\n"), /ChatPanel|ChatLauncher/, "chat must be available to read-only members too");
const hook = read("../src/features/chat/useDiagramChat.js");
assert.match(hook, /encodeURIComponent\(before\)/, "pagination cursor must be URL-encoded (timezone offsets contain +)");
assert.match(hook, /\/diagrams\/\$\{diagramId\}\/chat/);
const panel = read("../src/features/chat/ChatPanel.jsx");
assert.doesNotMatch(panel, /dangerouslySetInnerHTML/, "message content must render as text");
assert.match(panel, /role="log"/);
assert.match(panel, /maxLength=\{CHAT_MAX_LENGTH\}/);

// Thinking indicator: ai.thinking adds the question id, ai.done removes it by trigger id.
let thinking = addThinking([], { message_id: "q1", requester: "Ana" });
assert.equal(thinkingLabel(thinking), "La IA está respondiendo a Ana...");
assert.equal(addThinking(thinking, { message_id: "q1", requester: "Ana" }).length, 1, "same question twice must not duplicate");
thinking = addThinking(thinking, { message_id: "q2", requester: "Beto" });
assert.equal(thinkingLabel(thinking), "La IA está respondiendo a Ana y Beto...");
assert.equal(thinkingLabel(addThinking(thinking, { message_id: "q3", requester: "Caro" })), "La IA está respondiendo a Ana y 2 más...");
assert.equal(thinkingLabel(removeThinking(thinking, "q1")), "La IA está respondiendo a Beto...");
assert.equal(thinkingLabel([]), "");

// AI messages: the Hecho / No hice sections become lists, everything else stays text.
const blocks = parseAiMessage("Ana, listo.\n\nHecho:\n• Creé la clase Pedido\n• Relacioné Cliente con Pedido (association)\n\nNo hice:\n• Ya existía: x");
assert.deepEqual(blocks.map((b) => b.type), ["text", "list", "list"]);
assert.deepEqual(blocks[1], { type: "list", title: "Hecho", tone: "done", items: ["Creé la clase Pedido", "Relacioné Cliente con Pedido (association)"] });
assert.equal(blocks[2].tone, "skipped");
assert.deepEqual(parseAiMessage("Hecho:"), [{ type: "text", text: "Hecho:" }], "a title without items is plain text");
assert.deepEqual(parseAiMessage(""), []);

// @ia autocomplete.
for (const draft of ["@", "@i", "@ia", "hola @", "hola\n@i"]) assert.equal(mentionOpen(draft), true, draft);
for (const draft of ["", "hola", "mail@", "@ia ", "@iax", "@x"]) assert.equal(mentionOpen(draft), false, draft);
assert.equal(applyMention("@"), "@ia ");
assert.equal(applyMention("hola @i"), "hola @ia ");

// Wiring of the AI presence.
const hookSource = read("../src/features/chat/useDiagramChat.js");
assert.match(hookSource, /ai\.thinking/); assert.match(hookSource, /ai\.done/); assert.match(hookSource, /event\.trigger_id/);
assert.match(read("../src/features/chat/useAiHighlight.js"), /changed_class_ids/);
assert.match(read("../src/features/chat/useAiSettings.js"), /ai\.settings/);
assert.match(read("../src/features/canvas/ClassCard.jsx"), /ai-changed/);
assert.match(read("../src/features/canvas/RelationLayer.jsx"), /aiChangedIds\.includes\(relation\.id\)/);
assert.match(board, /useAiHighlight\(collaboration\.subscribe\)/);
assert.match(board, /canManage: owner/, "only the owner gets the AI switches");
assert.match(board, /aiHighlight\.classIds\.includes\(item\.id\)/);
assert.doesNotMatch(read("../src/features/chat/ChatPanel.jsx") + read("../src/features/chat/AiSettings.jsx"), /dangerouslySetInnerHTML/);
console.log("Chat checks passed.");
