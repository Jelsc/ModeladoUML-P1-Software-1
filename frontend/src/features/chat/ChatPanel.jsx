import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { AiSettings } from "./AiSettings.jsx";
import { CHAT_MAX_LENGTH, applyMention, authorLabel, canSend, clipText, formatChatTime, isOwnMessage, mentionOpen, parseAiMessage, replyPreview } from "./chat-model.js";

function AiMessageBody({ content }) {
  return parseAiMessage(content).map((block, index) => block.type === "list"
    ? <div key={index} className={`board-chat-ai-list ${block.tone}`}><b>{block.title}</b><ul>{block.items.map((item, itemIndex) => <li key={itemIndex}>{item}</li>)}</ul></div>
    : <p key={index}>{block.text}</p>);
}

export function ChatPanel({ messages, loading, hasMore, error, sending, thinking = "", aiSettings = null, currentUserId, onSend, onLoadOlder, onDismissError, onClose }) {
  const [draft, setDraft] = useState(""), [replyTo, setReplyTo] = useState(null);
  const listRef = useRef(null), inputRef = useRef(null), followBottom = useRef(true);
  useEffect(() => { inputRef.current?.focus({ preventScroll: true }); }, []);
  useLayoutEffect(() => { const list = listRef.current; if (list && followBottom.current) list.scrollTop = list.scrollHeight; }, [messages]);
  const onScroll = () => { const list = listRef.current; if (list) followBottom.current = list.scrollHeight - list.scrollTop - list.clientHeight < 48; };
  const loadOlder = async () => {
    const list = listRef.current, previousHeight = list?.scrollHeight || 0;
    followBottom.current = false;
    await onLoadOlder();
    requestAnimationFrame(() => { if (list) list.scrollTop += list.scrollHeight - previousHeight; });
  };
  const submit = async () => {
    if (!canSend(draft) || sending) return;
    if (await onSend(draft.trim(), replyTo?.id ?? null)) { setDraft(""); setReplyTo(null); followBottom.current = true; inputRef.current?.focus(); }
  };
  const onKeyDown = (event) => {
    if (event.key === "Escape") { event.stopPropagation(); onClose(); }
    else if (event.key === "Tab" && !event.shiftKey && mentionOpen(draft)) { event.preventDefault(); setDraft(applyMention(draft)); }
    else if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); submit(); }
  };
  const nearLimit = draft.length > CHAT_MAX_LENGTH - 200;
  return <section className="board-chat-panel" role="dialog" aria-label="Chat del equipo" onKeyDown={onKeyDown}>
    <header className="board-chat-header"><h2>Chat del equipo</h2><button type="button" className="ghost" onClick={onClose} aria-label="Cerrar chat">Cerrar</button></header>
    <ol ref={listRef} className="board-chat-list" role="log" aria-live="polite" aria-label="Mensajes" onScroll={onScroll}>
      {hasMore && <li className="board-chat-older"><button type="button" className="ghost" onClick={loadOlder}>Cargar mensajes anteriores</button></li>}
      {loading && <li className="board-chat-empty">Cargando mensajes...</li>}
      {!loading && messages.length === 0 && <li className="board-chat-empty">Todavía no hay mensajes. Escriba el primero.</li>}
      {messages.map((message) => {
        const own = isOwnMessage(message, currentUserId), quote = replyPreview(message, messages);
        return <li key={message.id} className={`board-chat-message${own ? " own" : ""}${message.author_kind === "ai" ? " ai" : ""}`}>
          <div className="board-chat-meta"><b>{own ? "Usted" : authorLabel(message)}{message.author_kind === "ai" && <span className="board-chat-ai-tag">asistente</span>}</b><time dateTime={message.created_at}>{formatChatTime(message.created_at)}</time></div>
          {quote && <blockquote className="board-chat-quote"><b>{quote.author}</b> {quote.text}</blockquote>}
          {message.author_kind === "ai" ? <AiMessageBody content={message.content} /> : <p>{message.content}</p>}
          <button type="button" className="ghost board-chat-reply" onClick={() => { setReplyTo(message); inputRef.current?.focus(); }} aria-label={`Responder a ${authorLabel(message)}`}>Responder</button>
        </li>;
      })}
    </ol>
    {thinking && <p className="board-chat-thinking" role="status"><span className="board-chat-dots" aria-hidden="true"><i /><i /><i /></span>{thinking}</p>}
    {aiSettings && <AiSettings {...aiSettings} />}
    {error && <p className="error board-chat-error" role="alert">{error} <button type="button" className="ghost" onClick={onDismissError}>Ocultar</button></p>}
    <form className="board-chat-form" onSubmit={(event) => { event.preventDefault(); submit(); }}>
      {replyTo && <p className="board-chat-replying">Respondiendo a <b>{authorLabel(replyTo)}</b>: {clipText(replyTo.content, 60)} <button type="button" className="ghost" onClick={() => setReplyTo(null)} aria-label="Cancelar respuesta">Quitar</button></p>}
      <textarea ref={inputRef} value={draft} onChange={(event) => setDraft(event.target.value)} rows={2} maxLength={CHAT_MAX_LENGTH} placeholder="Escriba un mensaje (Enter envía, Shift+Enter salta de línea)" aria-label="Mensaje" />
      {mentionOpen(draft) && <button type="button" className="board-chat-mention" onMouseDown={(event) => event.preventDefault()} onClick={() => { setDraft(applyMention(draft)); inputRef.current?.focus(); }}><b>@ia</b> Pedirle algo a la IA <small>(Tab)</small></button>}
      <div className="board-chat-actions">{nearLimit && <small className="muted">{draft.length}/{CHAT_MAX_LENGTH}</small>}<button type="submit" disabled={!canSend(draft) || sending}>{sending ? "Enviando..." : "Enviar"}</button></div>
    </form>
  </section>;
}
