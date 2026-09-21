import assert from 'node:assert/strict';
import { endpointLabelGeometry, endpointLabelPosition, selfLoopGeometry } from '../src/relation-geometry.js';
import { readFileSync } from 'node:fs';

const { ENDPOINT_GAP, NORMAL_OFFSET, DOWNWARD_BIAS } = endpointLabelGeometry;
const horizontal = endpointLabelPosition({ x: 100, y: 100 }, { x: 1, y: 0 }, 'source');
const vertical = endpointLabelPosition({ x: 100, y: 100 }, { x: 0, y: 1 }, 'source');

assert.equal(horizontal.x, 100 + ENDPOINT_GAP);
assert.equal(horizontal.y, 100 + NORMAL_OFFSET + DOWNWARD_BIAS);
assert.equal(vertical.x, 100 - NORMAL_OFFSET);
assert.equal(vertical.y, 100 + ENDPOINT_GAP + DOWNWARD_BIAS);
assert.ok(ENDPOINT_GAP > 14, 'label tangent gap must clear the largest endpoint marker');
assert.ok(NORMAL_OFFSET >= 12, 'label normal gap must remain readable');
const loopBox = { center: { x: 100, y: 100 }, width: 100, height: 80 };
const loop = selfLoopGeometry(loopBox);
const loopTargetLabel = endpointLabelPosition(loop.targetEdge, loop.targetTangent, 'target');
assert.equal(loop.sourceTangent.x, 1);
assert.equal(loop.targetTangent.x, -1);
assert.ok(loopTargetLabel.x > loopBox.center.x + loopBox.width / 2, 'self-loop target label must remain outside the class bounds');
assert.equal(endpointLabelPosition({ x: 100, y: 100 }, { x: 1, y: 0 }, 'source').x, 128, 'normal relation source labels must remain unchanged');
const relationLayer = readFileSync(new URL('../src/features/canvas/RelationLayer.jsx', import.meta.url), 'utf8');
const relationGeometry = readFileSync(new URL('../src/relation-geometry.js', import.meta.url), 'utf8');
assert.match(relationLayer, /selfLoopGeometry/);
assert.match(relationLayer, /sourceEdge.*targetEdge/);
assert.match(relationGeometry, /path: `M .* C /);
assert.match(relationGeometry, /targetTangent: \{ x: -1, y: 0 \}/);
console.log('relation geometry check passed');
