import assert from 'node:assert/strict';
import { classifyGesture, clampZoom, MAX_ZOOM, MIN_ZOOM, panPosition, zoomAnchorPan, zoomedCanvasPoint, zoomPercent } from '../src/canvas-geometry.js';

assert.equal(clampZoom(0), MIN_ZOOM);
assert.equal(clampZoom(3), MAX_ZOOM);
assert.equal(clampZoom(1.25), 1.25);
assert.equal(zoomPercent(0.75), '75%');
assert.deepEqual(
  zoomedCanvasPoint(
    { clientX: 130, clientY: 90 },
    { getBoundingClientRect: () => ({ left: 10, top: 10 }) },
    2,
    { x: 50, y: 20 },
  ),
  { x: 35, y: 30 },
);
assert.deepEqual(zoomAnchorPan({ x: 85, y: 50 }, { x: 100, y: 80 }, 1.5), { x: -27.5, y: 5 });
assert.deepEqual(panPosition({ x: 10, y: 20 }, { x: 35, y: 5 }, { x: 100, y: 80 }), { x: 125, y: 65 });
assert.equal(classifyGesture({ x: 3, y: 4 }, 2), 'pending');
assert.equal(classifyGesture({ x: 18, y: 0 }, 2), 'pan');
assert.equal(classifyGesture({ x: 2, y: 1 }, 18), 'pinch');
console.log('Zoom geometry checks passed.');
