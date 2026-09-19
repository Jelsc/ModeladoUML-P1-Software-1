import assert from 'node:assert/strict';
import { endpointLabelGeometry, endpointLabelPosition } from '../src/relation-geometry.js';

const { ENDPOINT_GAP, NORMAL_OFFSET, DOWNWARD_BIAS } = endpointLabelGeometry;
const horizontal = endpointLabelPosition({ x: 100, y: 100 }, { x: 1, y: 0 }, 'source');
const vertical = endpointLabelPosition({ x: 100, y: 100 }, { x: 0, y: 1 }, 'source');

assert.equal(horizontal.x, 100 + ENDPOINT_GAP);
assert.equal(horizontal.y, 100 + NORMAL_OFFSET + DOWNWARD_BIAS);
assert.equal(vertical.x, 100 - NORMAL_OFFSET);
assert.equal(vertical.y, 100 + ENDPOINT_GAP + DOWNWARD_BIAS);
assert.ok(ENDPOINT_GAP > 14, 'label tangent gap must clear the largest endpoint marker');
assert.ok(NORMAL_OFFSET >= 12, 'label normal gap must remain readable');
console.log('relation geometry check passed');
