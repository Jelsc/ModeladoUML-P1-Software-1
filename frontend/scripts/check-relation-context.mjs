import assert from 'node:assert/strict';
import { endpointMatches, normalizeEndpointContext, relationContext } from '../src/relation-context.js';

const relation = {
  id: 'r1', source_id: 10, target_id: '20',
  source_endpoint: null, source_endpoint_type: 'class',
  target_endpoint: null, target_endpoint_type: 'attributes',
  source_endpoint_info: { id: null, class: 'Order', type: 'class' },
  target_endpoint_info: { id: 'a2', class: 'Customer', type: 'attribute' },
};
const context = relationContext(relation);
assert.equal(context.source.endpointType, 'class');
assert.equal(context.target.endpointType, 'attribute');
assert.equal(context.target.endpointId, 'a2');
assert.ok(endpointMatches(context.target, 20, 'attributes', 'a2'));
assert.ok(!endpointMatches(context.target, 20, 'method', 'a2'));
assert.equal(normalizeEndpointContext({ source_id: '30', source_endpoint: 'm1', source_endpoint_type: 'method' }, 'source').endpointId, 'm1');
console.log('Relation context checks passed.');
