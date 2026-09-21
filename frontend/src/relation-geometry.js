const ENDPOINT_GAP = 28;
const NORMAL_OFFSET = 16;
const DOWNWARD_BIAS = 5;

function number(value, fallback = 0) {
  return Number.isFinite(Number(value)) ? Number(value) : fallback;
}

function orientedNormal(tangent) {
  let normal = { x: -tangent.y, y: tangent.x };
  if (Math.abs(tangent.y) < 0.35 && normal.y < 0) normal = { x: -normal.x, y: -normal.y };
  return normal;
}

export function endpointLabelPosition(edge, tangent, side) {
  const normal = orientedNormal(tangent);
  const direction = side === 'source' ? 1 : -1;
  return {
    x: edge.x + tangent.x * ENDPOINT_GAP * direction + normal.x * NORMAL_OFFSET,
    y: edge.y + tangent.y * ENDPOINT_GAP * direction + normal.y * NORMAL_OFFSET + DOWNWARD_BIAS,
  };
}

export function selfLoopGeometry(box, offset = 0) {
  const exitX = box.center.x + box.width / 2;
  const spread = Math.max(18, box.height * 0.18);
  const sourceEdge = { x: exitX, y: box.center.y - spread };
  const targetEdge = { x: exitX, y: box.center.y + spread };
  const control = { x: exitX + box.width * 0.72 + offset, y: box.center.y };
  return {
    sourceEdge,
    targetEdge,
    control,
    path: `M ${sourceEdge.x} ${sourceEdge.y} C ${control.x} ${sourceEdge.y} ${control.x} ${targetEdge.y} ${targetEdge.x} ${targetEdge.y}`,
    labelPoint: { x: control.x + 8, y: control.y },
    sourceTangent: { x: 1, y: 0 },
    targetTangent: { x: -1, y: 0 },
  };
}

export const endpointLabelGeometry = { ENDPOINT_GAP, NORMAL_OFFSET, DOWNWARD_BIAS };
