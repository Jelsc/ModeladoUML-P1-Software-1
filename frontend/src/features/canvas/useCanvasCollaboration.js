import { useCallback, useEffect, useRef, useState } from "react";
import { json, notifyAuthExpired, request } from "../../api.js";
import { zoomedCanvasPoint } from "../../canvas-geometry.js";
import { text } from "../../lib/diagram-normalizers.js";

const EPHEMERAL_EVENT_INTERVAL_MS = 16;
const cursorColor = (userId) => ["#ef8354", "#6bc9ae", "#8e9cff", "#e3b341", "#df79b8"][Math.abs(Number(userId) || 0) % 5];

export function useCanvasCollaboration({ id, currentUser, canvasRef, zoomRef, panRef, readOnly, refresh, mutate, pendingMutations, setError }) {
  const [remoteCursors, setRemoteCursors] = useState({}), [visualPositions, setVisualPositions] = useState({});
  const wsRef = useRef(null), eventTimers = useRef({}), eventPending = useRef({}), eventSequences = useRef({}), cursorTimers = useRef({}), visualFrame = useRef(null), livePositions = useRef({}), remoteCursorPositions = useRef({}), draggingClasses = useRef(new Set()), classDragCancels = useRef(new Map());
  const refreshRef = useRef(refresh), mutateRef = useRef(mutate), readOnlyRef = useRef(readOnly);
  refreshRef.current = refresh; mutateRef.current = mutate; readOnlyRef.current = readOnly;
  const scheduleVisualUpdate = useCallback(() => {
    if (visualFrame.current !== null) return;
    visualFrame.current = requestAnimationFrame(() => { visualFrame.current = null; setVisualPositions({ ...livePositions.current }); setRemoteCursors({ ...remoteCursorPositions.current }); });
  }, []);
  const sendEphemeral = useCallback((event, payload, key = event) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    eventPending.current[key] = payload;
    if (eventTimers.current[key]) return;
    eventTimers.current[key] = setTimeout(() => { const next = eventPending.current[key]; delete eventPending.current[key]; eventTimers.current[key] = null; if (next && wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify({ event, ...next })); }, EPHEMERAL_EVENT_INTERVAL_MS);
  }, []);
  const flushEphemeral = useCallback((event, key = event) => {
    const next = eventPending.current[key]; if (!next) return;
    clearTimeout(eventTimers.current[key]); eventTimers.current[key] = null; delete eventPending.current[key];
    if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify({ event, ...next }));
  }, []);
  useEffect(() => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/diagrams/${id}/ws?token=${encodeURIComponent(localStorage.getItem("token"))}`);
    wsRef.current = ws;
    ws.onmessage = (message) => {
      let event; try { event = JSON.parse(message.data); } catch { return; }
      if (String(event.user_id) === String(currentUser.id)) return;
      if (event.event === "cursor.move") {
        const sequence = Number(event.seq) || 0, key = `cursor:${event.user_id}`;
        if (sequence < (eventSequences.current[key] || 0)) return;
        eventSequences.current[key] = sequence; remoteCursorPositions.current[event.user_id] = { userId: event.user_id, x: Number(event.x), y: Number(event.y), name: text(event.user_name, "Colaborador"), color: cursorColor(event.user_id) }; scheduleVisualUpdate();
        clearTimeout(cursorTimers.current[event.user_id]); cursorTimers.current[event.user_id] = setTimeout(() => { delete remoteCursorPositions.current[event.user_id]; scheduleVisualUpdate(); }, 10000);
      } else if (event.event === "presence.leave") { clearTimeout(cursorTimers.current[event.user_id]); delete remoteCursorPositions.current[event.user_id]; scheduleVisualUpdate();
      } else if (event.event === "class.move") {
        const key = `class:${event.user_id}:${event.class_id}`, sequence = Number(event.seq) || 0;
        if (sequence < (eventSequences.current[key] || 0)) return;
        eventSequences.current[key] = sequence; livePositions.current[event.class_id] = { x: Number(event.x), y: Number(event.y) }; scheduleVisualUpdate();
      } else if (event.event === "class.updated") { const classId = event.class?.id; if (classId && !draggingClasses.current.has(classId)) { delete livePositions.current[classId]; scheduleVisualUpdate(); } if (!pendingMutations.current) refreshRef.current().catch((e) => setError(e.message));
      } else if (!pendingMutations.current) refreshRef.current().catch((e) => setError(e.message));
    };
    ws.onclose = (event) => { wsRef.current = null; setRemoteCursors({}); if (event.code === 1008 && localStorage.getItem("token")) notifyAuthExpired(); };
    ws.onerror = () => {};
    return () => { ws.close(); wsRef.current = null; Object.values(eventTimers.current).forEach(clearTimeout); Object.values(cursorTimers.current).forEach(clearTimeout); if (visualFrame.current !== null) cancelAnimationFrame(visualFrame.current); visualFrame.current = null; eventTimers.current = {}; eventPending.current = {}; remoteCursorPositions.current = {}; setRemoteCursors({}); };
  }, [id, currentUser.id, scheduleVisualUpdate, setError]);
  const drag = useCallback((e, item) => {
    if (e.pointerType === "touch" || e.button !== 0 || e.target.closest("button") || readOnlyRef.current) return;
    const point = (event) => zoomedCanvasPoint(event, canvasRef.current, zoomRef.current, panRef.current), start = point(e), x = Number(item.x) || 0, y = Number(item.y) || 0; let position = { x, y }; const pointerId = e.pointerId;
    draggingClasses.current.add(item.id);
    const cancel = (event) => { if (event?.pointerId != null && event.pointerId !== pointerId) return; removeEventListener("pointermove", move); removeEventListener("pointerup", up); removeEventListener("pointercancel", cancel); draggingClasses.current.delete(item.id); delete livePositions.current[item.id]; scheduleVisualUpdate(); classDragCancels.current.delete(pointerId); };
    const move = (event) => { if (event.pointerId !== pointerId) return; const current = point(event); position = { x: Math.max(8, Math.round(x + current.x - start.x)), y: Math.max(8, Math.round(y + current.y - start.y)) }; livePositions.current[item.id] = position; scheduleVisualUpdate(); const sequence = (eventSequences.current[`local:${item.id}`] || 0) + 1; eventSequences.current[`local:${item.id}`] = sequence; sendEphemeral("class.move", { class_id: item.id, ...position, seq: sequence }, item.id); };
    const up = async (event) => { if (event.pointerId !== pointerId) return; removeEventListener("pointermove", move); removeEventListener("pointerup", up); removeEventListener("pointercancel", cancel); flushEphemeral("class.move", item.id); try { if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(item.id || "")) throw Error("El identificador de clase no es válido. Actualice el diagrama e intente nuevamente."); await mutateRef.current(() => request(`/classes/${item.id}`, json("PATCH", { x: Number(position.x), y: Number(position.y) }))); delete livePositions.current[item.id]; setVisualPositions({ ...livePositions.current }); } catch (error) { delete livePositions.current[item.id]; setVisualPositions({ ...livePositions.current }); setError(error.message); await refreshRef.current(); } finally { draggingClasses.current.delete(item.id); classDragCancels.current.delete(pointerId); } };
    classDragCancels.current.set(pointerId, cancel); addEventListener("pointermove", move); addEventListener("pointerup", up); addEventListener("pointercancel", cancel);
  }, [canvasRef, flushEphemeral, panRef, scheduleVisualUpdate, sendEphemeral, setError, zoomRef]);
  const cancelClassDrag = useCallback(() => [...classDragCancels.current.values()].forEach((stop) => stop()), []);
  const sendCursor = useCallback((event) => { if (!canvasRef.current) return; const point = zoomedCanvasPoint(event, canvasRef.current, zoomRef.current, panRef.current); const seq = (eventSequences.current.cursor || 0) + 1; eventSequences.current.cursor = seq; sendEphemeral("cursor.move", { ...point, seq }); }, [canvasRef, panRef, sendEphemeral, zoomRef]);
  return { remoteCursors, visualPositions, drag, sendCursor, cancelClassDrag };
}
