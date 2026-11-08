function ChatIcon() {
  return <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.4A8 8 0 1 1 21 12Z" /></svg>;
}

// Top bar button that opens/closes the docked team chat. Shows unread count and a pulse while the AI is answering.
export function ChatLauncher({ onToggle, open = false, unread = 0, thinking = false }) {
  const label = unread > 0 ? `Chat del equipo, ${unread} mensajes sin leer` : "Chat del equipo";
  return <button type="button" className={`chat-topbar-button${thinking ? " thinking" : ""}${open ? " active" : ""}`} onClick={onToggle} aria-pressed={open} aria-label={thinking ? `${label}, la IA está respondiendo` : label} title={thinking ? "La IA está respondiendo..." : open ? "Cerrar el chat" : "Abrir el chat"}><ChatIcon />Chat{thinking && <span className="board-chat-pulse" aria-hidden="true" />}{unread > 0 && <span className="board-chat-badge" aria-hidden="true">{unread > 99 ? "99+" : unread}</span>}</button>;
}
