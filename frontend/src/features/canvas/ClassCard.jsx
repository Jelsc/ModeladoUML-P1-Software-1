import { endpointMatches } from "../../relation-context.js";
import { list } from "../../lib/diagram-normalizers.js";

export function ClassCard({ item, readOnly, relationContext: activeRelationContext, onSelect, onRelation, onDrag, onResize }) {
  if (readOnly) onDrag = () => {};
  const endpoints = [activeRelationContext?.source, activeRelationContext?.target].filter(Boolean), highlighted = endpoints.some((endpoint) => String(endpoint.classId ?? "") === String(item.id));
  const rowClass = (type, id) => endpoints.some((endpoint) => endpointMatches(endpoint, item.id, type, id)) ? "endpoint-highlight" : "";
  return <article ref={(node) => node && onResize(item.id, { width: node.offsetWidth, height: node.offsetHeight })} className={`class-card ${readOnly ? "read-only" : ""} ${highlighted ? "relation-endpoint-highlight" : ""}`} style={{ left: item.x, top: item.y }} onPointerDown={(e) => onDrag(e, item)} onClick={() => onSelect(item.id)}><div className="class-title"><b>{item.name}</b>{!readOnly && <button className="mini relation-action" onClick={(e) => { e.stopPropagation(); onRelation(item.id); }}>＋ Relación</button>}</div><div className="class-section">{list(item.attributes).map((a) => <div className={rowClass("attribute", a.id)} key={a.id}><span>{a.name}</span><small>{a.type}</small></div>)}</div><div className="class-section">{list(item.methods).map((m) => <div className={rowClass("method", m.id)} key={m.id}><span>{m.name}()</span><small>{m.type}</small></div>)}</div></article>;
}
