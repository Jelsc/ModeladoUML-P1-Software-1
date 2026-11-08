import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const pages = readFileSync(new URL('../src/pages/board-canvas.jsx', import.meta.url), 'utf8');
const gestures = readFileSync(new URL('../src/features/canvas/useCanvasGestures.js', import.meta.url), 'utf8');
const collaboration = readFileSync(new URL('../src/features/canvas/useCanvasCollaboration.js', import.meta.url), 'utf8');
const interaction = `${pages}\n${gestures}\n${collaboration}`;
const styles = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');

// Moving a class or a relation must not open the inspector: only a real click selects.
import { CLICK_MOVE_TOLERANCE, isClick, pressPoint } from '../src/features/canvas/click-guard.js';
const at = (x, y) => ({ clientX: x, clientY: y });
assert.equal(isClick(pressPoint(at(100, 100)), at(100, 100)), true, 'a still click selects');
assert.equal(isClick(pressPoint(at(100, 100)), at(100 + CLICK_MOVE_TOLERANCE, 100)), true, 'a tiny hand tremor still counts as a click');
assert.equal(isClick(pressPoint(at(100, 100)), at(180, 100)), false, 'a drag does not select');
assert.equal(isClick(pressPoint(at(100, 100)), at(103, 105)), false, 'diagonal distance is measured as a real distance');
assert.equal(isClick(null, at(5, 5)), true, 'keyboard activation has no press and must keep working');
const cardSource = readFileSync(new URL('../src/features/canvas/ClassCard.jsx', import.meta.url), 'utf8');
const relationSource = readFileSync(new URL('../src/features/canvas/RelationLayer.jsx', import.meta.url), 'utf8');
assert.match(cardSource, /onPointerDown=\{\(e\) => \{ press\.current = pressPoint\(e\);/); assert.match(cardSource, /if \(clicked\) onSelect\(item\.id\)/);
assert.match(relationSource, /onPointerDown=\{\(event\) => \{ press\.current = pressPoint\(event\);/); assert.match(relationSource, /if \(clicked\) onSelect\(relation\.id\)/);

assert.match(pages, /className="zoom-controls"/);
assert.match(interaction, /if \(event\.target\.closest\("\.zoom-controls"\)\) return/);
assert.match(interaction, /event\.preventDefault\(\);[\s\S]{0,180}changeZoom\(/);
assert.match(interaction, /event\.button !== 2/);
assert.match(interaction, /panPosition\(/);
assert.match(interaction, /setPointerCapture/);
assert.match(interaction, /mode: "pending"/);
assert.match(interaction, /classifyGesture\(/);
assert.match(interaction, /e\.pointerType === "touch" \|\| e\.button !== 0/);
assert.match(interaction, /event\.pointerId !== pointerId/);
assert.match(interaction, /classDragCancels\.current/);
assert.match(interaction, /activePointers\.current\.size === 2/);
assert.match(interaction, /gesture\.current = null/);
assert.match(pages, /activeRelationContext = hoverContext \|\| relationContext\(selectedRelation\)/);
assert.match(pages, /relationContext=\{activeRelationContext\}/);
assert.match(interaction, /gesturestart.*gesturechange.*gestureend.*touchmove/s);
assert.match(interaction, /event\.ctrlKey|event\.preventDefault\(\);\s*changeZoom/s);
assert.match(pages, /onContextMenu=\{\(event\) => event\.preventDefault\(\)\}/);
assert.match(styles, /\.canvas\s*\{[\s\S]*overflow:\s*hidden;/);
assert.match(styles, /\.canvas\s*\{[\s\S]*overscroll-behavior:\s*none;/);
assert.match(styles, /\.canvas\s*\{[\s\S]*touch-action:\s*none;/);
assert.match(styles, /\.zoom-controls\s*\{[\s\S]*position:\s*absolute;/);
console.log('Canvas interaction checks passed.');
