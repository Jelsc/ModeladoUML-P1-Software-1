import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { associationLinkGeometry, selfLoopGeometry, selfLoopMidpoint } from "../src/relation-geometry.js";
import { isManyToMany, maxIsMany, touchesMultiplicity } from "../src/features/relations/association-class.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const rel = (source_multiplicity, target_multiplicity, extra = {}) => ({ type: "association", source_multiplicity, target_multiplicity, ...extra });

for (const value of ["*", "0..*", "1..*", "n..*", " * "]) assert.equal(maxIsMany(value), true, value);
for (const value of ["1", "0..1", "", null, undefined, "1..5"]) assert.equal(maxIsMany(value), false, String(value));
assert.equal(isManyToMany(rel("*", "0..*")), true);
assert.equal(isManyToMany(rel("1", "*")), false);
assert.equal(isManyToMany(rel(null, null)), false, "null multiplicity is unspecified, not many");
assert.equal(isManyToMany(rel("*", "*", { type: "composition" })), false);
assert.equal(isManyToMany(rel("*", "*", { source_endpoint_type: "attribute" })), false);
assert.equal(touchesMultiplicity({ label: "x" }), false);
assert.equal(touchesMultiplicity({ target_multiplicity: "*" }), true);

// Dashed link starts at the relation midpoint and ends on the association class border.
const box = { center: { x: 300, y: 400 }, width: 200, height: 100 };
assert.deepEqual(associationLinkGeometry({ x: 300, y: 200 }, box), { from: { x: 300, y: 200 }, to: { x: 300, y: 350 } });
assert.deepEqual(associationLinkGeometry({ x: 0, y: 400 }, box).to, { x: 200, y: 400 });
const loop = selfLoopGeometry({ center: { x: 100, y: 100 }, width: 200, height: 100 });
assert.equal(selfLoopMidpoint(loop).y, 100);

const board = read("../src/pages/board-canvas.jsx");
const hook = read("../src/features/relations/useAssociationClassPrompt.js");
assert.match(board, /associationClass\.inspect\(selectedRelationId, patch, next\)/);
assert.match(board, /<AssociationClassModal/);
assert.match(board, /associationClass\.inspect\(created\?\.id, payload, next\)/, "relations created as M:N must also prompt");
const layer = read("../src/features/canvas/RelationLayer.jsx");
assert.match(layer, /relation\.association_class_id/);
assert.match(layer, /className="association-link"/);
assert.match(hook, /relation\.association_class_id/, "already linked relations must not reopen the modal");
assert.match(hook, /\/association-class/);
assert.match(hook, /converting\.current/);
assert.doesNotMatch(hook, /useEffect/, "the prompt must not react to realtime refreshes");
console.log("Association class checks passed.");
