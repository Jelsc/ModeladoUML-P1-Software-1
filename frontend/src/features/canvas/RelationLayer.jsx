import { endpointLabelPosition } from "../../relation-geometry.js";
import { relationContext } from "../../relation-context.js";

function relationKey(relation) {
  return [relation?.source_id, relation?.target_id].sort().join(":");
}

function number(value, fallback = 0) {
  return Number.isFinite(Number(value)) ? Number(value) : fallback;
}

export function intersectRectangle(center, direction, size) {
  const dx = number(direction.x), dy = number(direction.y);
  const halfWidth = Math.max(number(size.width, 210) / 2, 1);
  const halfHeight = Math.max(number(size.height, 80) / 2, 1);
  const scale = Math.max(Math.abs(dx) / halfWidth, Math.abs(dy) / halfHeight, 0.0001);
  return { x: center.x + dx / scale, y: center.y + dy / scale };
}

export function classGeometry(item, dimensions = {}) {
  const width = number(dimensions.width, 210);
  const height = number(dimensions.height, 47 + 16 + (item?.attributes?.length || 0) * 26 + 16 + (item?.methods?.length || 0) * 26);
  return { center: { x: number(item?.x) + width / 2, y: number(item?.y) + height / 2 }, width, height };
}

function pointOnQuadratic(start, control, end, t = 0.5) {
  const inverse = 1 - t;
  return { x: inverse * inverse * start.x + 2 * inverse * t * control.x + t * t * end.x, y: inverse * inverse * start.y + 2 * inverse * t * control.y + t * t * end.y };
}

function unitVector(vector, fallback = { x: 1, y: 0 }) {
  const length = Math.hypot(number(vector?.x), number(vector?.y));
  return length ? { x: number(vector.x) / length, y: number(vector.y) / length } : fallback;
}

function markerFor(relation, side) {
  if (side === "source" && relation.type === "composition") return "url(#uml-composition-filled)";
  if (side === "source" && relation.type === "aggregation") return "url(#uml-aggregation-hollow)";
  if (side === "target" && relation.type === "inheritance") return "url(#uml-inheritance-hollow)";
  if (side === "target" && relation.type === "dependency") return "url(#uml-dependency-open)";
  return undefined;
}

export function RelationLayer({ diagram, classDimensions = {}, selectedId, hoveredId, onSelect, onHover }) {
  const relations = Array.isArray(diagram?.relations) ? diagram.relations : [];
  const classes = Array.isArray(diagram?.classes) ? diagram.classes : [];
  const groups = {};
  relations.forEach((relation) => { const key = relationKey(relation); (groups[key] ||= []).push(relation); });

  return <svg className="relations" aria-label="Relaciones"><defs>
    <marker id="uml-composition-filled" markerWidth="14" markerHeight="14" refX="12" refY="7" orient="auto-start-reverse" markerUnits="userSpaceOnUse"><path className="marker-composition" d="M0 7 L7 0 L14 7 L7 14 Z" /></marker>
    <marker id="uml-aggregation-hollow" markerWidth="14" markerHeight="14" refX="12" refY="7" orient="auto-start-reverse" markerUnits="userSpaceOnUse"><path className="marker-hollow" d="M0 7 L7 0 L14 7 L7 14 Z" /></marker>
    <marker id="uml-inheritance-hollow" markerWidth="15" markerHeight="15" refX="14" refY="7.5" orient="auto" markerUnits="userSpaceOnUse"><path className="marker-hollow" d="M0 0 L14 7.5 L0 15 Z" /></marker>
    <marker id="uml-dependency-open" markerWidth="12" markerHeight="12" refX="11" refY="6" orient="auto" markerUnits="userSpaceOnUse"><path className="marker-open" d="M0 0 L11 6 L0 12" fill="none" stroke="context-stroke" /></marker>
  </defs>{relations.map((relation) => {
    const sourceClass = classes.find((item) => item?.id === relation?.source_id);
    const targetClass = classes.find((item) => item?.id === relation?.target_id);
    if (!sourceClass || !targetClass) return null;
    const sourceBox = classGeometry(sourceClass, classDimensions[sourceClass.id]);
    const targetBox = classGeometry(targetClass, classDimensions[targetClass.id]);
    const x1 = sourceBox.center.x, y1 = sourceBox.center.y;
    const x2 = targetBox.center.x, y2 = targetBox.center.y;
    const group = groups[relationKey(relation)] || [relation];
    const offset = (group.indexOf(relation) - (group.length - 1) / 2) * 28;
    const dx = x2 - x1, dy = y2 - y1, length = Math.hypot(dx, dy) || 1;
    const nx = -dy / length, ny = dx / length;
    const cx = (x1 + x2) / 2 + nx * offset, cy = (y1 + y2) / 2 + ny * offset;
    const sourceEdge = intersectRectangle(sourceBox.center, { x: cx - x1, y: cy - y1 }, sourceBox);
    const targetEdge = intersectRectangle(targetBox.center, { x: cx - x2, y: cy - y2 }, targetBox);
    const lineDx = targetEdge.x - sourceEdge.x, lineDy = targetEdge.y - sourceEdge.y;
    const lineLength = Math.hypot(lineDx, lineDy) || 1;
    const ux = lineDx / lineLength, uy = lineDy / lineLength;
    const labelPoint = pointOnQuadratic(sourceEdge, { x: cx, y: cy }, targetEdge);
    const labelX = labelPoint.x + nx * 12, labelY = labelPoint.y + ny * 12;
    const sourceTangent = unitVector({ x: cx - sourceEdge.x, y: cy - sourceEdge.y }, { x: ux, y: uy });
    const targetTangent = unitVector({ x: targetEdge.x - cx, y: targetEdge.y - cy }, { x: ux, y: uy });
    const sourceLabel = endpointLabelPosition(sourceEdge, sourceTangent, "source");
    const targetLabel = endpointLabelPosition(targetEdge, targetTangent, "target");
    const className = `relation ${relation.type || "association"} ${selectedId === relation.id ? "selected" : ""} ${hoveredId === relation.id ? "hovered" : ""}`;
    return <g key={relation.id} className={className} onMouseEnter={() => onHover(relationContext(relation))} onMouseLeave={() => onHover(null)} onClick={() => onSelect(relation.id)}>
      <path className="relation-hit" d={`M ${sourceEdge.x} ${sourceEdge.y} Q ${cx} ${cy} ${targetEdge.x} ${targetEdge.y}`} />
      <path className="relation-line" d={`M ${sourceEdge.x} ${sourceEdge.y} Q ${cx} ${cy} ${targetEdge.x} ${targetEdge.y}`} markerStart={markerFor(relation, "source")} markerEnd={markerFor(relation, "target")} />
      {relation.source_multiplicity && <text className="multiplicity" x={sourceLabel.x} y={sourceLabel.y} textAnchor="middle">{relation.source_multiplicity}</text>}
      {relation.target_multiplicity && <text className="multiplicity" x={targetLabel.x} y={targetLabel.y} textAnchor="middle">{relation.target_multiplicity}</text>}
      {relation.label && <text className="relation-label" x={labelX} y={labelY} textAnchor="middle">{relation.label}</text>}
    </g>;
  })}</svg>;
}
