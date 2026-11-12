import { useEffect, useState } from "react";
import { request } from "../../api.js";

// Photo attached to a chat message. It is fetched with the session token (an <img src> cannot send it) and shown from a local blob URL.
export function ChatImage({ diagramId, image }) {
  const [url, setUrl] = useState(""), [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true, objectUrl = "";
    setUrl(""); setFailed(false);
    request(`/diagrams/${diagramId}/chat-images/${image.id}`)
      .then((blob) => { if (!alive) return; objectUrl = URL.createObjectURL(blob); setUrl(objectUrl); })
      .catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [diagramId, image.id]);
  if (failed) return <p className="muted board-chat-image-missing">La foto ya no está disponible.</p>;
  if (!url) return <p className="muted board-chat-image-missing" role="status">Cargando foto…</p>;
  return <a className="board-chat-image-link" href={url} target="_blank" rel="noreferrer" title="Abrir la foto en tamaño completo"><img className="board-chat-image" src={url} alt={image.name ? `Foto enviada: ${image.name}` : "Foto enviada al chat"} /></a>;
}
