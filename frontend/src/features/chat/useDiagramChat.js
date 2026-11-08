import { useCallback, useEffect, useRef, useState } from "react";
import { json, request } from "../../api.js";
import { CHANNELS, CHAT_PAGE_SIZE, DEFAULT_CHANNEL, THINKING_TTL_MS, addThinking, bumpUnread, clearUnread, emptyChats, emptyUnread, isOwnMessage, mergeMessages, messageChannel, oldestCreatedAt, removeThinking, totalUnread } from "./chat-model.js";

// The three team chats (diseno / desarrollo / test). History comes from REST; live messages come from the board WebSocket through `subscribe`.
export function useDiagramChat({ diagramId, currentUserId, subscribe, open }) {
  const [channel, setChannel] = useState(DEFAULT_CHANNEL), [chats, setChats] = useState(emptyChats), [error, setError] = useState(""), [sending, setSending] = useState(false), [unreadByChannel, setUnreadByChannel] = useState(emptyUnread), [thinking, setThinking] = useState([]);
  const thinkingTimers = useRef(new Map());
  const openRef = useRef(open), channelRef = useRef(channel), chatsRef = useRef(chats);
  openRef.current = open; channelRef.current = channel; chatsRef.current = chats;
  const patchChat = useCallback((id, change) => setChats((current) => ({ ...current, [id]: { ...current[id], ...change(current[id]) } })), []);
  useEffect(() => {
    let alive = true;
    setChats(emptyChats()); setUnreadByChannel(emptyUnread()); setError(""); setThinking([]);
    CHANNELS.forEach(({ id }) => request(`/diagrams/${diagramId}/chat?limit=${CHAT_PAGE_SIZE}&channel=${id}`)
      .then((page) => { if (alive) patchChat(id, (chat) => ({ messages: mergeMessages(chat.messages, page), hasMore: page.length === CHAT_PAGE_SIZE })); })
      .catch((e) => { if (alive) setError(e.message); })
      .finally(() => { if (alive) patchChat(id, () => ({ loading: false })); }));
    return () => { alive = false; };
  }, [diagramId, patchChat]);
  useEffect(() => {
    const timers = thinkingTimers.current, stop = (messageId) => { clearTimeout(timers.get(messageId)); timers.delete(messageId); setThinking((current) => removeThinking(current, messageId)); };
    const unsubscribe = subscribe((event) => {
      if (event.event === "ai.thinking" && event.message_id) { setThinking((current) => addThinking(current, event)); clearTimeout(timers.get(event.message_id)); timers.set(event.message_id, setTimeout(() => stop(event.message_id), THINKING_TTL_MS)); return; }
      if (event.event === "ai.done") { stop(event.trigger_id); return; }
      if (event.event !== "chat.message" || !event.message) return;
      const id = messageChannel(event.message);
      patchChat(id, (chat) => ({ messages: mergeMessages(chat.messages, [event.message]) }));
      if ((!openRef.current || channelRef.current !== id) && !isOwnMessage(event.message, currentUserId)) setUnreadByChannel((current) => bumpUnread(current, id));
    });
    return () => { unsubscribe(); timers.forEach(clearTimeout); timers.clear(); };
  }, [subscribe, currentUserId, patchChat]);
  useEffect(() => { if (open) setUnreadByChannel((current) => clearUnread(current, channel)); }, [open, channel]);
  const loadOlder = useCallback(async () => {
    const id = channelRef.current, before = oldestCreatedAt(chatsRef.current[id].messages);
    if (!before) return;
    try {
      const page = await request(`/diagrams/${diagramId}/chat?limit=${CHAT_PAGE_SIZE}&channel=${id}&before=${encodeURIComponent(before)}`);
      patchChat(id, (chat) => ({ messages: mergeMessages(chat.messages, page), hasMore: page.length === CHAT_PAGE_SIZE }));
    } catch (e) { setError(e.message); }
  }, [diagramId, patchChat]);
  const send = useCallback(async (content, replyToId = null, target = channelRef.current) => {
    setSending(true); setError("");
    try { const saved = await request(`/diagrams/${diagramId}/chat`, json("POST", { content, reply_to_id: replyToId, channel: target })); patchChat(target, (chat) => ({ messages: mergeMessages(chat.messages, [saved]) })); return true; }
    catch (e) { setError(e.message); return false; }
    finally { setSending(false); }
  }, [diagramId, patchChat]);
  const dismissError = useCallback(() => setError(""), []);
  const active = chats[channel];
  return { channel, setChannel, messages: active.messages, loading: active.loading, hasMore: active.hasMore, error, sending, unread: totalUnread(unreadByChannel), unreadByChannel, thinking, send, loadOlder, dismissError };
}
