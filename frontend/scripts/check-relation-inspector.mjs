import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/features/diagram/inspector/RelationInspector.jsx', import.meta.url), 'utf8');

assert.match(source, /const \[labelDraft, setLabelDraft\] = useState\(""\)/);
assert.match(source, /setLabelDraft\(relation\?\.label \|\| ""\)/);
assert.match(source, /const saveLabel = \(\) => \{[\s\S]*onPatch\(\{ label: labelDraft \}\)/);
assert.match(source, /value=\{labelDraft\}[\s\S]*onBlur=\{saveLabel\}/);
assert.match(source, /e\.key === "Enter"\) e\.currentTarget\.blur\(\)/);
assert.doesNotMatch(source, /onChange=\{\(e\) => onPatch\(\{ label: e\.target\.value \}\)\}/);
console.log('Relation inspector checks passed.');
