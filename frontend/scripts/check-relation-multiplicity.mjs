import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { directionalMultiplicityLabel, relationMultiplicityPayload, relationMultiplicityPreview } from "../src/features/relations/multiplicity-direction.js";

const modal = readFileSync(new URL("../src/features/relations/RelationModal.jsx", import.meta.url), "utf8");
const inspector = readFileSync(new URL("../src/features/diagram/inspector/RelationInspector.jsx", import.meta.url), "utf8");

const payload = relationMultiplicityPayload("1", "1..*");
assert.deepEqual(payload, { source_multiplicity: "1", target_multiplicity: "1..*" });
assert.equal(relationMultiplicityPreview("A", "B", payload.source_multiplicity, payload.target_multiplicity), "A 1 — 1..* B");
assert.equal(directionalMultiplicityLabel("A", "B", "target"), "De A hacia B");
assert.equal(directionalMultiplicityLabel("A", "B", "source"), "De B hacia A");
assert.equal(directionalMultiplicityLabel("A", "A", "target", true), "De A hacia A (extremo destino)");
assert.match(modal, /setMultiplicityChoice\("target", value\)/);
assert.match(modal, /setMultiplicityChoice\("source", value\)/);
assert.match(inspector, /field\("target", targetLabel\).*field\("source", sourceLabel\)/);
assert.match(inspector, /onPatch\(\{ \[field\]: value \|\| null \}\)/);
console.log("Relation multiplicity checks passed.");
