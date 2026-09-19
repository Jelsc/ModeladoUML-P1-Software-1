function MicrophoneIcon({ className = "", title = "" }) {
  return <svg className={className} viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden={title ? undefined : "true"} aria-label={title || undefined} focusable="false" role={title ? "img" : undefined}>{title && <title>{title}</title>}<rect x="8" y="3" width="8" height="12" rx="4" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6" /></svg>;
}

export { MicrophoneIcon };
export function AssistantLauncher({ onOpen, launcherRef }) {
  const stopCanvasInteraction = (event) => event.stopPropagation();
  return <div ref={launcherRef} className="assistant-launcher"><button type="button" className="ghost assistant-launcher-button" onPointerDown={stopCanvasInteraction} onClick={onOpen} aria-label="Abrir Asistente" title="Abrir Asistente"><MicrophoneIcon />Asistente</button></div>;
}
