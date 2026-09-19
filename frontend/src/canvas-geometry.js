export const MIN_ZOOM = 0.25;
export const MAX_ZOOM = 2;
export const ZOOM_STEP = 0.25;
export const GESTURE_THRESHOLD = 8;

export function clampZoom(value) {
  const numeric = Number(value);
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Number.isFinite(numeric) ? numeric : 1));
}

export function zoomedCanvasPoint(event, canvas, zoom = 1, pan = { x: 0, y: 0 }) {
  const rect = canvas.getBoundingClientRect();
  const scale = clampZoom(zoom);
  return {
    x: Math.max(0, Math.round((event.clientX - rect.left - pan.x) / scale)),
    y: Math.max(0, Math.round((event.clientY - rect.top - pan.y) / scale)),
  };
}

export function zoomAnchorPan(logicalPoint, viewportPoint, zoom) {
  const scale = clampZoom(zoom);
  return {
    x: viewportPoint.x - logicalPoint.x * scale,
    y: viewportPoint.y - logicalPoint.y * scale,
  };
}

export function panPosition(start, current, initialPan) {
  return {
    x: initialPan.x + current.x - start.x,
    y: initialPan.y + current.y - start.y,
  };
}

export function classifyGesture(midpointDelta, distanceDelta, threshold = GESTURE_THRESHOLD) {
  const panDistance = Math.hypot(Number(midpointDelta?.x) || 0, Number(midpointDelta?.y) || 0);
  const pinchDistance = Math.abs(Number(distanceDelta) || 0);
  if (panDistance < threshold && pinchDistance < threshold) return "pending";
  return pinchDistance > panDistance ? "pinch" : "pan";
}

export function zoomPercent(zoom) {
  return `${Math.round(clampZoom(zoom) * 100)}%`;
}
