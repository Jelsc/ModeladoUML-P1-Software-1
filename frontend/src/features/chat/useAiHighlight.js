import { useEffect, useRef, useState } from "react";
import { AI_HIGHLIGHT_MS } from "./chat-model.js";

// Classes and relations the AI just changed, announced by `ai.done` (applied directly) or `ai.proposals` (a proposal was accepted); cleared after a few seconds.
export function useAiHighlight(subscribe) {
  const [highlight, setHighlight] = useState({ classIds: [], relationIds: [] }), timer = useRef(null);
  useEffect(() => {
    const unsubscribe = subscribe((event) => {
      if (event.event !== "ai.done" && event.event !== "ai.proposals") return;  // ai.proposals carries the changed ids when a member accepts a proposal
      const classIds = Array.isArray(event.changed_class_ids) ? event.changed_class_ids : [], relationIds = Array.isArray(event.changed_relation_ids) ? event.changed_relation_ids : [];
      if (!classIds.length && !relationIds.length) return;
      setHighlight({ classIds, relationIds }); clearTimeout(timer.current);
      timer.current = setTimeout(() => setHighlight({ classIds: [], relationIds: [] }), AI_HIGHLIGHT_MS);
    });
    return () => { unsubscribe(); clearTimeout(timer.current); };
  }, [subscribe]);
  return highlight;
}
