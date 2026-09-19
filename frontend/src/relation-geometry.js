const ENDPOINT_GAP = 28;
const NORMAL_OFFSET = 16;
const DOWNWARD_BIAS = 5;

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

export const endpointLabelGeometry = { ENDPOINT_GAP, NORMAL_OFFSET, DOWNWARD_BIAS };
