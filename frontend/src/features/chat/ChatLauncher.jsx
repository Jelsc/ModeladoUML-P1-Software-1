function ChatIcon() {
  return <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.4A8 8 0 1 1 21 12Z" /></svg>;
}

export function ChatLauncher({ onOpen, unread = 0, thinking = false, launcherRef }) {
  const label = unread > 0 ? `Abrir chat, ${unread} mensajes sin leer` : "Abrir chat";
  return <button ref={launcherRef} type="button" className={`board-chat-launcher${thinking ? " thinking" : ""}`} onClick={onOpen} aria-label={thinking ? `${label}, la IA está respondiendo` : label} title={thinking ? "La IA está respondiendo..." : "Abrir chat"}><ChatIcon />Chat{thinking && <span className="board-chat-pulse" aria-hidden="true" />}{unread > 0 && <span className="board-chat-badge" aria-hidden="true">{unread > 99 ? "99+" : unread}</span>}</button>;
}
