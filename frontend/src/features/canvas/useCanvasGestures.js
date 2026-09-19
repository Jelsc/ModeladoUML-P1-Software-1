import { useEffect, useRef, useState } from "react";
import { clampZoom, classifyGesture, MIN_ZOOM, panPosition, zoomAnchorPan, ZOOM_STEP } from "../../canvas-geometry.js";

export function useCanvasGestures({ id, canvasRef, cancelClassDrag, zoomRef: externalZoomRef, panRef: externalPanRef }) {
  const zoomKey = `uml:board:${id}:zoom`;
  const [zoom, setZoom] = useState(() => clampZoom(Number(localStorage.getItem(zoomKey)) || 1));
  const [isPanning, setIsPanning] = useState(false), [pan, setPan] = useState({ x: 0, y: 0 });
  const localZoomRef = useRef(zoom), localPanRef = useRef({ x: 0, y: 0 });
  const zoomRef = externalZoomRef || localZoomRef, panRef = externalPanRef || localPanRef, panning = useRef(null), activePointers = useRef(new Map()), gesture = useRef(null);
  useEffect(() => { localStorage.setItem(zoomKey, String(zoom)); zoomRef.current = zoom; }, [zoom, zoomKey]);
  useEffect(() => {
    const canvas = canvasRef.current; if (!canvas) return undefined;
    const preventNativeGesture = (event) => event.preventDefault();
    const types = ["gesturestart", "gesturechange", "gestureend", "touchstart", "touchmove", "touchend", "touchcancel"];
    types.forEach((type) => canvas.addEventListener(type, preventNativeGesture, { passive: false }));
    return () => types.forEach((type) => canvas.removeEventListener(type, preventNativeGesture));
  }, [canvasRef]);
  function changeZoom(nextZoom, event) {
    const next = clampZoom(nextZoom), current = zoomRef.current, canvas = canvasRef.current; if (next === current || !canvas) return;
    const rect = canvas.getBoundingClientRect(), viewportPoint = event ? { x: event.clientX - rect.left, y: event.clientY - rect.top } : { x: rect.width / 2, y: rect.height / 2 }, logicalPoint = { x: (viewportPoint.x - panRef.current.x) / current, y: (viewportPoint.y - panRef.current.y) / current }, nextPan = zoomAnchorPan(logicalPoint, viewportPoint, next);
    zoomRef.current = next; panRef.current = nextPan; setPan(nextPan); setZoom(next);
  }
  function handleWheel(event) {
    if (event.target.closest(".zoom-controls")) return; event.preventDefault();
    if (event.ctrlKey || event.metaKey) return changeZoom(zoomRef.current - event.deltaY * 0.01, event);
    const isMouseWheel = event.deltaMode !== 0 || (event.deltaX === 0 && event.deltaY % 10 === 0 && Math.abs(event.deltaY) >= 40);
    if (isMouseWheel) changeZoom(zoomRef.current + (event.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP), event);
    else { const nextPan = { x: panRef.current.x - event.deltaX, y: panRef.current.y - event.deltaY }; panRef.current = nextPan; setPan(nextPan); }
  }
  function startPan(event) {
    if (event.pointerType === "touch") { activePointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY }); if (activePointers.current.size === 2) { cancelClassDrag?.(); const points = [...activePointers.current.values()], midpoint = { x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2 }, distance = Math.hypot(points[1].x - points[0].x, points[1].y - points[0].y) || 1, rect = canvasRef.current.getBoundingClientRect(), viewport = { x: midpoint.x - rect.left, y: midpoint.y - rect.top }; gesture.current = { mode: "pending", startMidpoint: midpoint, startDistance: distance, zoom: zoomRef.current, pan: { ...panRef.current }, anchor: { x: (viewport.x - panRef.current.x) / zoomRef.current, y: (viewport.y - panRef.current.y) / zoomRef.current } }; setIsPanning(true); event.preventDefault(); } canvasRef.current?.setPointerCapture?.(event.pointerId); return; }
    if (event.button !== 2 || event.target.closest(".zoom-controls")) return; panning.current = { pointerId: event.pointerId, start: { x: event.clientX, y: event.clientY }, moved: false, initialPan: { ...panRef.current } }; canvasRef.current.setPointerCapture?.(event.pointerId); event.preventDefault();
  }
  function movePan(event) {
    if (event.pointerType === "touch") { if (!activePointers.current.has(event.pointerId)) return; activePointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY }); if (activePointers.current.size < 2 || !gesture.current) return; const points = [...activePointers.current.values()], midpoint = { x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2 }, distance = Math.hypot(points[1].x - points[0].x, points[1].y - points[0].y) || 1, current = gesture.current, midpointDelta = { x: midpoint.x - current.startMidpoint.x, y: midpoint.y - current.startMidpoint.y }, distanceDelta = distance - current.startDistance; if (current.mode === "pending") current.mode = classifyGesture(midpointDelta, distanceDelta); if (current.mode === "pending") return; const nextZoom = current.mode === "pinch" ? clampZoom(current.zoom * distance / current.startDistance) : current.zoom, rect = canvasRef.current.getBoundingClientRect(), nextPan = current.mode === "pinch" ? { x: midpoint.x - rect.left - current.anchor.x * nextZoom, y: midpoint.y - rect.top - current.anchor.y * nextZoom } : { x: current.pan.x + midpointDelta.x, y: current.pan.y + midpointDelta.y }; zoomRef.current = nextZoom; panRef.current = nextPan; setZoom(nextZoom); setPan(nextPan); setIsPanning(true); event.preventDefault(); return; }
    const current = panning.current; if (!current || event.pointerId !== current.pointerId) return; const nextPan = panPosition(current.start, { x: event.clientX, y: event.clientY }, current.initialPan); current.moved = current.moved || event.clientX !== current.start.x || event.clientY !== current.start.y; setIsPanning(true); panRef.current = nextPan; setPan(nextPan); event.preventDefault();
  }
  function endPan(event) { if (event.pointerType === "touch") { activePointers.current.delete(event.pointerId); gesture.current = null; if (!activePointers.current.size) setIsPanning(false); canvasRef.current?.releasePointerCapture?.(event.pointerId); return; } if (!panning.current || event.pointerId !== panning.current.pointerId) return; canvasRef.current.releasePointerCapture?.(event.pointerId); panning.current = null; setIsPanning(false); }
  return { zoom, pan, zoomRef, panRef, isPanning, changeZoom, handleWheel, startPan, movePan, endPan };
}
