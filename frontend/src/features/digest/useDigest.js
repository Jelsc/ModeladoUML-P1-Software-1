import { useCallback, useEffect, useRef, useState } from "react";
import { request } from "../../api.js";
import { hasDigest } from "./digest-model.js";

// "What happened while I was away". Reading never moves the cursor; it moves when the card is dismissed,
// when there was nothing to show, or when the member leaves after having seen the card.
export function useDigest(diagramId) {
  const [digest, setDigest] = useState(null), settled = useRef(false);
  const markSeen = useCallback(() => request(`/diagrams/${diagramId}/seen`, { method: "POST" }).catch(() => {}), [diagramId]);
  useEffect(() => {
    let alive = true; settled.current = false; setDigest(null);
    request(`/diagrams/${diagramId}/digest`).then((value) => {
      if (!alive) return;
      if (hasDigest(value)) setDigest(value); else { settled.current = true; markSeen(); }
    }).catch(() => {});
    return () => { alive = false; if (settled.current) markSeen(); };
  }, [diagramId, markSeen]);
  const dismiss = useCallback(() => { settled.current = true; setDigest(null); markSeen(); }, [markSeen]);
  // Hide without moving the cursor yet: the AI is about to read what was missed. It moves when the member leaves.
  const hide = useCallback(() => { settled.current = true; setDigest(null); }, []);
  return { digest, dismiss, hide };
}
