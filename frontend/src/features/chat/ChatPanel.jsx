import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { AiSettings } from "./AiSettings.jsx";
import { EndpointList } from "./EndpointList.jsx";
import { ProposalList } from "./ProposalList.jsx";
import { TestPanel } from "./TestPanel.jsx";
import { CHANNELS, CHAT_MAX_LENGTH, applyMention, authorLabel, canSend, channelOf, clipText, formatChatTime, isOwnMessage, mentionOpen, parseAiMessage, replyPreview, thinkingLabel } from "./chat-model.js";

function AiMessageBody({ content }) {
  return parseAiMessage(content).map((block, index) => block.type === "list"
    ? <div key={index} className={`board-chat-ai-list ${block.tone}`}><b>{block.title}</b><ul>{block.items.map((item, itemIndex) => <li key={itemIndex}>{item}</li>)}</ul></div>
    : <p key={index}>{block.text}</p>);
}

function MenuIcon() {
  return <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true" focusable="false"><path d="M4 7h16M4 12h16M4 17h10" /></svg>;
}

// Docked side panel (like a browser's AI sidebar): one fixed chat per area of the project, all collaborative and answered by the same AI.
export function ChatPanel({ channel, onChannel, unreadByChannel = {}, endpoints = null, proposals = null, tests = null, messages, loading, hasMore, error, sending, thinking = [], aiSettings = null, currentUserId, onSend, onLoadOlder, onDismissError, onClose }) {
  const [drafts, setDrafts] = useState({}), [replyTo, setReplyTo] = useState(null), [menuOpen, setMenuOpen] = useState(false);
  const listRef = useRef(null), inputRef = useRef(null), followBottom = useRef(true);
  const current = channelOf(channel), draft = drafts[current.id] || "", setDraft = (value) => setDrafts((all) => ({ ...all, [current.id]: value }));
  const thinkingText = thinkingLabel(thinking, current.id);
  useEffect(() => { setReplyTo(null); followBottom.current = true; }, [current.id]);
  useEffect(() => { if (!menuOpen) inputRef.current?.focus({ preventScroll: true }); }, [menuOpen, current.id]);
  useLayoutEffect(() => { const list = listRef.current; if (list && followBottom.current) list.scrollTop = list.scrollHeight; }, [messages, menuOpen, current.id]);
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
  const choose = (id) => { onChannel(id); setMenuOpen(false); };
  const onKeyDown = (event) => {
    if (event.key === "Escape") { event.stopPropagation(); if (menuOpen) setMenuOpen(false); else onClose(); }
    else if (menuOpen) return;
    else if (event.key === "Tab" && !event.shiftKey && mentionOpen(draft)) { event.preventDefault(); setDraft(applyMention(draft)); }
    else if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); submit(); }
  };
  const nearLimit = draft.length > CHAT_MAX_LENGTH - 200;
  return <section className="board-chat-panel board-chat-dock" role="dialog" aria-label={`Chat ${current.label}`} onKeyDown={onKeyDown}>
    <div className="board-chat-header">
      <button type="button" className="ghost board-chat-menu-button" onClick={() => setMenuOpen((open) => !open)} aria-expanded={menuOpen} aria-label="Ver chats del diagrama" title="Chats"><MenuIcon /></button>
      <div className="board-chat-title"><h2>{menuOpen ? "Chats" : current.label}</h2>{!menuOpen && <small>{current.hint}</small>}</div>
      <button type="button" className="ghost board-chat-close" onClick={onClose} aria-label="Cerrar chat" title="Cerrar">✕</button>
    </div>
    {menuOpen ? <nav className="board-chat-channels" aria-label="Chats del diagrama">
      <ul>{CHANNELS.map((item) => {
        const unread = unreadByChannel[item.id] || 0, busy = thinkingLabel(thinking, item.id) !== "";
        return <li key={item.id}><button type="button" className={`board-chat-channel${item.id === current.id ? " active" : ""}`} aria-current={item.id === current.id ? "true" : undefined} onClick={() => choose(item.id)}>
          <span><b>{item.label}</b><small>{item.hint}</small></span>
          {busy && <span className="board-chat-dots" aria-label="La IA está respondiendo"><i /><i /><i /></span>}
          {unread > 0 && <span className="board-chat-badge inline" aria-label={`${unread} mensajes sin leer`}>{unread > 99 ? "99+" : unread}</span>}
        </button></li>;
      })}</ul>
      <p className="board-chat-channels-note">Los tres chats son del equipo, se crean con el diagrama y usan la misma IA. La IA modifica el diagrama en Diseño y Desarrollo; Test es solo de consulta.</p>
    </nav> : <>
      <ol ref={listRef} className="board-chat-list" role="log" aria-live="polite" aria-label="Mensajes" onScroll={onScroll}>
        {hasMore && <li className="board-chat-older"><button type="button" className="ghost" onClick={loadOlder}>Cargar mensajes anteriores</button></li>}
        {loading && <li className="board-chat-empty">Cargando mensajes...</li>}
        {!loading && messages.length === 0 && <li className="board-chat-empty">Todavía no hay mensajes en {current.label}. Escriba el primero.</li>}
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
      {(current.id === "diseno" || current.id === "desarrollo") && proposals && <ProposalList {...proposals} />}
      {current.id === "test" && tests && <TestPanel {...tests} />}
      {(current.id === "desarrollo" || current.id === "test") && endpoints && <EndpointList {...endpoints} canEdit={endpoints.canEdit && current.id === "desarrollo"} testRun={current.id === "test" ? tests?.data?.latest : null} />}
      {thinkingText && <p className="board-chat-thinking" role="status"><span className="board-chat-dots" aria-hidden="true"><i /><i /><i /></span>{thinkingText}</p>}
      {aiSettings && <AiSettings {...aiSettings} />}
      {error && <p className="error board-chat-error" role="alert">{error} <button type="button" className="ghost" onClick={onDismissError}>Ocultar</button></p>}
      <form className="board-chat-form" onSubmit={(event) => { event.preventDefault(); submit(); }}>
        {replyTo && <p className="board-chat-replying">Respondiendo a <b>{authorLabel(replyTo)}</b>: {clipText(replyTo.content, 60)} <button type="button" className="ghost" onClick={() => setReplyTo(null)} aria-label="Cancelar respuesta">Quitar</button></p>}
        <textarea ref={inputRef} value={draft} onChange={(event) => setDraft(event.target.value)} rows={2} maxLength={CHAT_MAX_LENGTH} placeholder={current.placeholder} aria-label="Mensaje" />
        {mentionOpen(draft) && <button type="button" className="board-chat-mention" onMouseDown={(event) => event.preventDefault()} onClick={() => { setDraft(applyMention(draft)); inputRef.current?.focus(); }}><b>@ia</b> Pedirle algo a la IA <small>(Tab)</small></button>}
        <div className="board-chat-actions">{nearLimit && <small className="muted">{draft.length}/{CHAT_MAX_LENGTH}</small>}<button type="submit" disabled={!canSend(draft) || sending}>{sending ? "Enviando..." : "Enviar"}</button></div>
      </form>
    </>}
  </section>;
}
