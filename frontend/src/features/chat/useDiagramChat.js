import { useCallback, useEffect, useRef, useState } from "react";
import { json, request } from "../../api.js";
import { CHAT_PAGE_SIZE, THINKING_TTL_MS, addThinking, isOwnMessage, mergeMessages, oldestCreatedAt, removeThinking } from "./chat-model.js";

// History comes from REST; live messages come from the board WebSocket through `subscribe`.
export function useDiagramChat({ diagramId, currentUserId, subscribe, open }) {
  const [messages, setMessages] = useState([]), [loading, setLoading] = useState(true), [hasMore, setHasMore] = useState(false), [error, setError] = useState(""), [sending, setSending] = useState(false), [unread, setUnread] = useState(0), [thinking, setThinking] = useState([]);
  const thinkingTimers = useRef(new Map());
  const openRef = useRef(open), messagesRef = useRef(messages);
  openRef.current = open; messagesRef.current = messages;
  useEffect(() => {
    let alive = true;
    setMessages([]); setUnread(0); setError(""); setLoading(true); setThinking([]);
    request(`/diagrams/${diagramId}/chat?limit=${CHAT_PAGE_SIZE}`)
      .then((page) => { if (!alive) return; setMessages((current) => mergeMessages(current, page)); setHasMore(page.length === CHAT_PAGE_SIZE); })
      .catch((e) => { if (alive) setError(e.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [diagramId]);
  useEffect(() => {
    const timers = thinkingTimers.current, stop = (messageId) => { clearTimeout(timers.get(messageId)); timers.delete(messageId); setThinking((current) => removeThinking(current, messageId)); };
    const unsubscribe = subscribe((event) => {
      if (event.event === "ai.thinking" && event.message_id) { setThinking((current) => addThinking(current, event)); clearTimeout(timers.get(event.message_id)); timers.set(event.message_id, setTimeout(() => stop(event.message_id), THINKING_TTL_MS)); return; }
      if (event.event === "ai.done") { stop(event.trigger_id); return; }
      if (event.event !== "chat.message" || !event.message) return;
      setMessages((current) => mergeMessages(current, [event.message]));
      if (!openRef.current && !isOwnMessage(event.message, currentUserId)) setUnread((count) => count + 1);
    });
    return () => { unsubscribe(); timers.forEach(clearTimeout); timers.clear(); };
  }, [subscribe, currentUserId]);
  useEffect(() => { if (open) setUnread(0); }, [open]);
  const loadOlder = useCallback(async () => {
    const before = oldestCreatedAt(messagesRef.current);
    if (!before) return;
    try {
      const page = await request(`/diagrams/${diagramId}/chat?limit=${CHAT_PAGE_SIZE}&before=${encodeURIComponent(before)}`);
      setMessages((current) => mergeMessages(current, page)); setHasMore(page.length === CHAT_PAGE_SIZE);
    } catch (e) { setError(e.message); }
  }, [diagramId]);
  const send = useCallback(async (content, replyToId = null) => {
    setSending(true); setError("");
    try { const saved = await request(`/diagrams/${diagramId}/chat`, json("POST", { content, reply_to_id: replyToId })); setMessages((current) => mergeMessages(current, [saved])); return true; }
    catch (e) { setError(e.message); return false; }
    finally { setSending(false); }
  }, [diagramId]);
  const dismissError = useCallback(() => setError(""), []);
  return { messages, loading, hasMore, error, sending, unread, thinking, send, loadOlder, dismissError };
}
