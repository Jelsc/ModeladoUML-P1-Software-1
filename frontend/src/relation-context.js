export function normalizeEndpointType(type) {
  const value = String(type || 'class').toLowerCase();
  if (value === 'attributes') return 'attribute';
  if (value === 'methods') return 'method';
  return value === 'attribute' || value === 'method' ? value : 'class';
}

export function normalizeEndpointContext(relation, side) {
  const info = relation?.[`${side}_endpoint_info`] || {};
  const classId = side === 'source' ? relation?.source_id : relation?.target_id;
  const endpointField = relation?.[`${side}_endpoint`];
  return {
    classId: info.class_id ?? info.classId ?? classId ?? null,
    endpointId: endpointField ?? info.id ?? info.endpoint_id ?? info.attribute_id ?? info.method_id ?? null,
    endpointType: normalizeEndpointType(relation?.[`${side}_endpoint_type`] ?? info.type),
  };
}

export function endpointMatches(endpoint, classId, endpointType, endpointId) {
  return String(endpoint?.classId ?? '') === String(classId ?? '') &&
    normalizeEndpointType(endpoint?.endpointType) === normalizeEndpointType(endpointType) &&
    String(endpoint?.endpointId ?? '') === String(endpointId ?? '');
}

export function relationContext(relation) {
  if (!relation || typeof relation !== 'object') return null;
  return {
    relationId: relation.id,
    source: normalizeEndpointContext(relation, 'source'),
    target: normalizeEndpointContext(relation, 'target'),
  };
}
