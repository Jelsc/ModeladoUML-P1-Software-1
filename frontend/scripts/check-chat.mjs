import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { endpointSummary, kindLabel, removeEndpoint, replaceEndpoint, sortEndpoints, statusLabel } from "../src/features/chat/endpoint-model.js";
import { CHANNELS, CHAT_MAX_LENGTH, addThinking, applyMention, authorLabel, bumpUnread, canSend, channelOf, clearUnread, clipText, emptyChats, emptyUnread, formatChatTime, isOwnMessage, mentionOpen, mergeMessages, messageChannel, oldestCreatedAt, parseAiMessage, parseServerDate, removeThinking, replyPreview, thinkingLabel, totalUnread } from "../src/features/chat/chat-model.js";

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

// The chat is sequential. A timestamp without offset is UTC (MongoDB hands them back naive); reading it as local time put history hours
// away from new messages and sent new ones to the top of the chat.
assert.equal(parseServerDate("2026-01-01T12:00:00.123"), Date.parse("2026-01-01T12:00:00.123Z"), "naive means UTC");
assert.equal(parseServerDate("2026-01-01T12:00:00+00:00"), Date.parse("2026-01-01T12:00:00Z")); assert.equal(parseServerDate("2026-01-01T08:00:00-04:00"), Date.parse("2026-01-01T12:00:00Z"));
assert.equal(parseServerDate("2026-01-01T12:00:00Z"), Date.parse("2026-01-01T12:00:00Z")); assert.ok(Number.isNaN(parseServerDate("nope")));
const mixed = mergeMessages([msg("history", 0, { created_at: "2026-01-01T12:00:00.000" })], [msg("fresh", 0, { created_at: "2026-01-01T12:05:00.000+00:00" })]);
assert.deepEqual(mixed.map((m) => m.id), ["history", "fresh"], "a new message goes to the END even when history had no offset");
const sameInstant = "2026-01-01T12:00:00.000+00:00";
assert.deepEqual(mergeMessages([msg("zz-answer", 0, { created_at: sameInstant, reply_to_id: "aa-question" })], [msg("aa-question", 0, { created_at: sameInstant })]).map((m) => m.id), ["aa-question", "zz-answer"], "an answer never sorts before its question");
assert.deepEqual(mergeMessages([msg("aa-answer", 0, { created_at: sameInstant, reply_to_id: "zz-question" })], [msg("zz-question", 0, { created_at: sameInstant })]).map((m) => m.id), ["zz-question", "aa-answer"], "even when the ids would say the opposite");
assert.equal(formatChatTime("2026-01-15T18:00:00.000", new Date(Date.UTC(2026, 0, 15, 20, 0, 0))).length, 5, "naive timestamps format as a clock for the same day");

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
assert.match(board, /chat=\{\{ open: chatOpen/, "the chat button lives in the top bar");
const topBarSource = read("../src/components/layout/TopBar.jsx");
assert.match(topBarSource, /<ChatLauncher /);
assert.ok(topBarSource.indexOf("Desplegar") < topBarSource.indexOf("<ChatLauncher ") && topBarSource.indexOf("<ChatLauncher ") < topBarSource.indexOf("theme-toggle"), "chat button sits between Desplegar and the theme toggle");
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
// Three fixed team chats: same AI, separated conversations. Only Diseño lets the AI edit the diagram.
assert.deepEqual(CHANNELS.map((c) => c.id), ["diseno", "desarrollo", "test"]);
assert.deepEqual(CHANNELS.map((c) => c.aiEdits), [true, true, false], "Diseño and Desarrollo edit; Test is consultation only");
assert.equal(channelOf("desarrollo").label, "Desarrollo");
assert.equal(channelOf("nope").id, "diseno", "unknown channel falls back to Diseño");
assert.equal(messageChannel({}), "diseno", "messages without channel belong to Diseño");
assert.equal(messageChannel({ channel: "test" }), "test");
assert.deepEqual(Object.keys(emptyChats()), ["diseno", "desarrollo", "test"]);
let unread = emptyUnread();
unread = bumpUnread(bumpUnread(unread, "test"), "test"); unread = bumpUnread(unread, "desarrollo");
assert.deepEqual(unread, { diseno: 0, desarrollo: 1, test: 2 }); assert.equal(totalUnread(unread), 3);
assert.deepEqual(clearUnread(unread, "test"), { diseno: 0, desarrollo: 1, test: 0 }); assert.equal(clearUnread(unread, "diseno"), unread, "nothing to clear keeps the same object");
// The thinking indicator is scoped to the chat where the question was asked.
let scoped = addThinking([], { message_id: "q1", requester: "Ana", channel: "desarrollo" }); scoped = addThinking(scoped, { message_id: "q2", requester: "Beto" });
assert.equal(thinkingLabel(scoped, "desarrollo"), "La IA está respondiendo a Ana..."); assert.equal(thinkingLabel(scoped, "diseno"), "La IA está respondiendo a Beto...", "no channel in the event means Diseño");
assert.equal(thinkingLabel(scoped, "test"), "");
// Wiring of the docked panel.
assert.match(hookSource, /channel=\$\{id\}/, "history is requested per chat"); assert.match(hookSource, /channel: target/, "messages are sent to the active chat");
assert.match(hookSource, /messageChannel\(event\.message\)/, "live messages go to their own chat");
assert.match(board, /chat-docked/); assert.match(board, /<ChatPanel channel=\{chat\.channel\} onChannel=\{chat\.setChannel\}/);
assert.match(board, /chat\.send\(SUMMARY_REQUEST, null, "diseno"\)/, "the digest summary is asked in Diseño");
const dockedPanel = read("../src/features/chat/ChatPanel.jsx");
assert.match(dockedPanel, /aria-label="Ver chats del diagrama"/); assert.match(dockedPanel, /CHANNELS\.map/);
assert.doesNotMatch(dockedPanel, /Nuevo chat/, "chats are fixed: there is no 'new chat' nor chat history");
assert.match(read("../src/style.css"), /\.app-shell\.chat-docked/);

// Endpoints designed by the AI: pending ones first, readable summary, immutable updates.
const ep = (id, status, name, cls = "Cliente") => ({ id, status, name, class_name: cls });
assert.deepEqual(sortEndpoints([ep("1", "approved", "a"), ep("2", "proposed", "z"), ep("3", "proposed", "b", "Aaa")]).map((e) => e.id), ["3", "2", "1"], "pending first, then class and name");
assert.equal(endpointSummary([]), "Sin endpoints de la IA");
assert.equal(endpointSummary([ep("1", "approved", "a")]), "1 endpoint · 1 aprobado · 0 pendientes");
assert.equal(endpointSummary([ep("1", "approved", "a"), ep("2", "proposed", "b"), ep("3", "proposed", "c")]), "3 endpoints · 1 aprobado · 2 pendientes");
assert.equal(statusLabel("proposed"), "Pendiente"); assert.equal(statusLabel("approved"), "Aprobado"); assert.equal(kindLabel("custom"), "Código personalizado"); assert.equal(kindLabel("raro"), "raro");
const eps = [ep("1", "proposed", "a")];
assert.equal(replaceEndpoint(eps, ep("1", "approved", "a"))[0].status, "approved"); assert.equal(eps[0].status, "proposed", "input must not be mutated");
assert.equal(replaceEndpoint(eps, ep("2", "proposed", "b")).length, 2); assert.deepEqual(removeEndpoint(eps, "1"), []);
const endpointsHook = read("../src/features/chat/useEndpoints.js");
assert.match(endpointsHook, /ai\.endpoints/, "the list refreshes when anyone proposes, approves or deletes"); assert.match(endpointsHook, /\/endpoints\/\$\{id\}/);
assert.match(dockedPanel, /\(current\.id === "desarrollo" \|\| current\.id === "test"\) && endpoints && <EndpointList/, "the endpoint list lives in the Desarrollo and Test chats (Test cannot approve)");
assert.match(board, /useEndpoints\(\{ diagramId: id, subscribe: collaboration\.subscribe \}\)/); assert.match(board, /canEdit: !readOnly/, "viewers cannot approve");
assert.doesNotMatch(read("../src/features/chat/EndpointList.jsx"), /dangerouslySetInnerHTML/);
assert.match(read("../src/features/deployment/DeploymentPanel.jsx"), /deployment\?\.warning_summary/, "the compile warning is shown in the deployment panel");
console.log("Chat checks passed.");
