import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { decisionNote, pendingProposals, proposalStatusLabel, proposalSummary, replaceProposal, sortProposals } from "../src/features/chat/proposal-model.js";
import { parseAiMessage } from "../src/features/chat/chat-model.js";

const item = (id, status, created_at, extra = {}) => ({ id, status, created_at, summary: ["Agregar el atributo age: integer a Customer"], requested_by: "Ana", decided_by: null, ...extra });

// summary line of the list
assert.equal(proposalSummary([]), "Sin propuestas de la IA");
assert.equal(proposalSummary([item("a", "accepted", "2026-01-01")]), "Sin propuestas pendientes");
assert.equal(proposalSummary([item("a", "pending", "2026-01-01")]), "1 propuesta pendiente de aprobación");
assert.equal(proposalSummary([item("a", "pending", "2026-01-01"), item("b", "pending", "2026-01-02")]), "2 propuestas pendientes de aprobación");
assert.deepEqual(pendingProposals([item("a", "pending", "x"), item("b", "rejected", "y")]).map((p) => p.id), ["a"]);

// pending first and oldest first (answered in the order asked); decided ones after, newest first
const sorted = sortProposals([item("old-ok", "accepted", "2026-01-01"), item("new-ok", "rejected", "2026-01-05"), item("p2", "pending", "2026-01-04"), item("p1", "pending", "2026-01-03")]);
assert.deepEqual(sorted.map((p) => p.id), ["p1", "p2", "new-ok", "old-ok"]);

// replacing keeps the others and appends unknown ones
const list = [item("a", "pending", "1"), item("b", "pending", "2")];
assert.deepEqual(replaceProposal(list, item("a", "accepted", "1")).map((p) => p.status), ["accepted", "pending"]);
assert.equal(replaceProposal(list, item("c", "pending", "3")).length, 3);

// who decided, in words
assert.equal(decisionNote(item("a", "pending", "1")), "Pedida por Ana");
assert.equal(decisionNote(item("a", "accepted", "1", { decided_by: "Beto" })), "Aceptada por Beto");
assert.equal(decisionNote(item("a", "rejected", "1", { decided_by: "Caro" })), "Rechazada por Caro");
assert.match(decisionNote(item("a", "stale", "1", { decided_by: "Beto" })), /Ya no se podía aplicar por Beto/);
assert.equal(proposalStatusLabel("stale"), "Ya no se podía aplicar");

// the AI's reply renders the proposal as its own list (not as plain text)
const blocks = parseAiMessage("Propongo agregarlo.\n\nPropuesta pendiente de aprobación:\n• Crear la clase Invoice\n• Agregar el atributo total: decimal a Invoice\n\nNo hice:\n• Algo");
assert.deepEqual(blocks.map((b) => b.type === "list" ? b.tone : b.type), ["text", "proposed", "skipped"]);
assert.deepEqual(blocks[1].items, ["Crear la clase Invoice", "Agregar el atributo total: decimal a Invoice"]);
assert.equal(parseAiMessage("Hecho:\n• x")[0].tone, "done", "the direct mode keeps its look");

// wiring (source checks, like the other feature checks)
const source = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), "utf8");
const panel = source("features/chat/ChatPanel.jsx"), board = source("pages/board-canvas.jsx"), hook = source("features/chat/useProposals.js");
assert.match(panel, /\(current\.id === "diseno" \|\| current\.id === "desarrollo"\) && proposals && <ProposalList/, "proposals live in the two chats where the AI edits");
assert.doesNotMatch(panel, /current\.id === "test"\) && proposals/, "Test is consultation only");
assert.match(board, /useProposals\(\{ diagramId: id, subscribe: collaboration\.subscribe \}\)/);
assert.match(board, /proposals=\{\{ items: proposals\.items, canEdit: !readOnly/, "read-only clients cannot decide");
assert.match(hook, /ai\.proposals/); assert.match(hook, /\/ai-proposals\/\$\{id\}\/\$\{verb\}/);
assert.match(source("features/chat/AiSettings.jsx"), /ai_requires_approval/);
assert.match(source("features/chat/useAiHighlight.js"), /ai\.proposals/, "accepting highlights what changed");

console.log("proposals check ok");
