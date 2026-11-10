import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { LAYOUT, accessLabel, clip, flowOutline, layoutFlow, relationLabel } from "../src/features/chat/flow-model.js";

const msg = (from, to, label, dashed = false) => ({ kind: "message", from, to, label, dashed });
const participants = ["client", "controller", "service", "repository", "db"].map((id) => ({ id, label: id }));
const flow = {
  participants,
  steps: [
    msg("client", "controller", "POST /x"), msg("controller", "service", "run(id)"),
    { kind: "alt", branches: [
      { label: "existe", steps: [msg("service", "repository", "findById"), { kind: "self", at: "service", label: "entity.set(true)" }, msg("repository", "service", "fila", true)] },
      { label: "no existe", steps: [{ kind: "loop", label: "para cada x", steps: [msg("service", "controller", "error", true)] }] },
    ] },
    msg("controller", "client", "200 OK", true),
  ],
};
const view = layoutFlow(flow);

// Columns: one per participant, evenly spaced, inside the margins.
assert.equal(view.width, LAYOUT.margin * 2 + LAYOUT.column * 5);
assert.deepEqual(view.participants.map((p) => p.x), [0, 1, 2, 3, 4].map((i) => LAYOUT.margin + LAYOUT.column / 2 + i * LAYOUT.column));
assert.equal(view.lifelines.length, 5); assert.ok(view.lifelines.every((line) => line.y2 > view.arrows.at(-1).y && line.y2 < view.height), "lifelines reach below the last step");

// Time flows downward: every row is strictly below the previous one, in step order.
const rows = [...view.arrows.map((a) => a.y), ...view.selfs.map((s) => s.y)].sort((a, b) => a - b);
assert.deepEqual(rows, [...new Set(rows)], "no two steps share a row");
assert.deepEqual(view.arrows.map((a) => a.label), ["POST /x", "run(id)", "findById", "fila", "error", "200 OK"]);
assert.ok(view.arrows.every((a, i, all) => i === 0 || a.y > all[i - 1].y), "arrows are emitted top to bottom");
assert.equal(view.arrows[0].direction, "right"); assert.equal(view.arrows[3].direction, "left", "a return goes back to the caller"); assert.equal(view.arrows[3].dashed, true); assert.equal(view.arrows[0].dashed, false);
assert.equal(view.selfs.length, 1); assert.equal(view.selfs[0].x, view.participants[2].x, "a self call sits on its own lifeline");

// Blocks: the alt box encloses all of its branches, the divider separates them, and a nested block is drawn inside its parent.
const alt = view.boxes.find((b) => b.tag === "alt"), loop = view.boxes.find((b) => b.tag === "bucle");
assert.ok(alt && loop); assert.equal(alt.label, "existe"); assert.equal(view.dividers.length, 1); assert.equal(view.dividers[0].label, "no existe");
const inside = (box, y) => y > box.y && y < box.y + box.h;
assert.ok(inside(alt, view.arrows[2].y) && inside(alt, view.arrows[3].y) && inside(alt, view.arrows[4].y) && inside(alt, view.selfs[0].y), "every step of both branches is inside the alt box");
assert.ok(!inside(alt, view.arrows[1].y) && !inside(alt, view.arrows[5].y), "steps outside the alt are not boxed");
assert.ok(view.dividers[0].y > view.arrows[3].y && view.dividers[0].y < view.arrows[4].y, "the divider sits between branch 1 and branch 2");
assert.ok(loop.depth === 1 && alt.depth === 0 && loop.x > alt.x && loop.x + loop.w < alt.x + alt.w && loop.y > alt.y && loop.y + loop.h < alt.y + alt.h, "the nested loop sits inside the alt");

// Robustness: empty flows, unknown participants and missing data never throw.
assert.equal(layoutFlow({ participants: [], steps: [] }).arrows.length, 0); assert.doesNotThrow(() => layoutFlow(null)); assert.doesNotThrow(() => layoutFlow({}));
assert.equal(layoutFlow({ participants, steps: [msg("client", "nobody", "x")] }).arrows.length, 0, "a step with an unknown participant is skipped");

// Text helpers.
assert.equal(clip("abc", 10), "abc"); assert.equal(clip("x".repeat(50), 10).length, 10); assert.equal(clip("a   b\n c"), "a b c"); assert.equal(clip(null), "");
const outline = flowOutline(flow).split("\n");
assert.equal(outline[0], "client → controller: POST /x"); assert.ok(outline.includes("si existe:") && outline.includes("sino si no existe:") && outline.includes("  repository ⇢ service: fila") && outline.includes("    repetir para cada x:") === false);
assert.ok(outline.includes("  repetir para cada x:") && outline.includes("    service ⇢ controller: error"));
assert.equal(accessLabel("lee y escribe"), "Lee y escribe"); assert.equal(accessLabel("raro"), "raro");
assert.equal(relationLabel({ other: "Pedido", type: "composition", multiplicity: "1 : *" }), "Pedido (composition, 1 : *)"); assert.equal(relationLabel({ other: "Pedido", type: "association" }), "Pedido (association)");

// Wiring: double click on an endpoint opens the diagram; Test lists the methods too but only Desarrollo can approve.
const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const list = read("../src/features/chat/EndpointList.jsx"), panel = read("../src/features/chat/ChatPanel.jsx"), board = read("../src/pages/board-canvas.jsx"), modal = read("../src/features/chat/MethodFlowModal.jsx"), hook = read("../src/features/chat/useMethodFlow.js"), css = read("../src/style.css");
assert.match(list, /onDoubleClick=\{onOpenFlow \? \(\) => onOpenFlow\(item\) : undefined\}/, "double click opens the flow");
assert.match(list, /Ver el ciclo de vida de \$\{item\.name\}/, "there is also a button, for keyboard and touch users");
assert.match(panel, /current\.id === "desarrollo" \|\| current\.id === "test"/); assert.match(panel, /canEdit=\{endpoints\.canEdit && current\.id === "desarrollo"\}/, "Test lists methods but does not approve them");
assert.match(board, /onOpenFlow: setFlowTarget/); assert.match(board, /\{flowTarget && <MethodFlowModal endpoint=\{flowTarget\}/);
assert.match(hook, /\/endpoints\/\$\{endpointId\}\/flow/);
assert.doesNotMatch(modal + list, /dangerouslySetInnerHTML/, "method text from the AI renders as text");
assert.match(modal, /event\.key === "Escape"/); assert.match(modal, /role="dialog" aria-modal="true"/); assert.match(modal, /navigator\.clipboard\.writeText\(flow\.mermaid\)/);
const zIndex = (selector) => Number((css.match(new RegExp(`${selector.replace(/[.]/g, "\\.")}\\s*\\{[^}]*z-index:\\s*(\\d+)`)) || [])[1]);
assert.ok(zIndex(".method-flow-backdrop") > zIndex(".board-chat-panel.board-chat-dock"), "the diagram opens above the chat panel");
console.log("Method flow checks passed.");
