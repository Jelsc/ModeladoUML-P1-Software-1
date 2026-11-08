import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { SUMMARY_REQUEST, digestActors, digestHeadline, formatAway, hasDigest, visibleItems } from "../src/features/digest/digest-model.js";

const digest = (extra = {}) => ({ since: "2026-01-01T10:00:00+00:00", activity: [], activity_total: 0, chat_total: 0, by_actor: {}, ...extra });
const item = (n) => ({ id: `a${n}`, summary: `cambio ${n}`, actor_kind: "user" });

// A card only appears for returning members when something happened.
assert.equal(hasDigest(null), false);
assert.equal(hasDigest(digest({ since: null, activity_total: 3 })), false, "first visit: nothing was missed");
assert.equal(hasDigest(digest()), false);
assert.equal(hasDigest(digest({ activity_total: 1 })), true);
assert.equal(hasDigest(digest({ chat_total: 2 })), true);

assert.equal(digestHeadline(digest({ activity_total: 1, chat_total: 1 })), "1 cambio y 1 mensaje");
assert.equal(digestHeadline(digest({ activity_total: 5 })), "5 cambios");
assert.equal(digestHeadline(digest({ chat_total: 3 })), "3 mensajes");
assert.equal(digestActors(digest({ by_actor: { Beto: 2, IA: 5, Ana: 2 } })), "IA (5), Ana (2), Beto (2)");
assert.equal(digestActors(digest()), "");

// Newest items are shown; the rest is announced as hidden using the real total.
const many = digest({ activity: Array.from({ length: 30 }, (_, i) => item(i)), activity_total: 41 });
const { shown, hidden } = visibleItems(many, 6);
assert.deepEqual(shown.map((x) => x.summary), ["cambio 24", "cambio 25", "cambio 26", "cambio 27", "cambio 28", "cambio 29"]);
assert.equal(hidden, 35);
assert.deepEqual(visibleItems(digest({ activity: [item(1)], activity_total: 1 })), { shown: [item(1)], hidden: 0 });

const now = new Date("2026-01-01T12:00:00+00:00");
assert.equal(formatAway("2026-01-01T11:59:50+00:00", now), "hace un momento");
assert.equal(formatAway("2026-01-01T11:30:00+00:00", now), "hace 30 min");
assert.equal(formatAway("2026-01-01T09:00:00+00:00", now), "hace 3 h");
assert.equal(formatAway("2025-12-31T10:00:00+00:00", now), "hace 1 día");
assert.equal(formatAway("2025-12-28T10:00:00+00:00", now), "hace 4 días");
assert.equal(formatAway("garbage", now), "");
assert.equal(formatAway("2026-01-02T12:00:00+00:00", now), "", "a future date (clock skew) shows nothing");
assert.match(SUMMARY_REQUEST, /^@ia /, "the summary button must invoke the AI");

// Wiring.
const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const hook = read("../src/features/digest/useDigest.js");
assert.match(hook, /\/diagrams\/\$\{diagramId\}\/digest/);
assert.match(hook, /\/diagrams\/\$\{diagramId\}\/seen/);
assert.match(hook, /if \(settled\.current\) markSeen\(\)/, "leaving only marks the diagram as seen if the card was handled (StrictMode-safe)");
const board = read("../src/pages/board-canvas.jsx");
assert.match(board, /useDigest\(id\)/);
assert.match(board, /<DigestCard /);
assert.match(board, /SUMMARY_REQUEST/);
assert.doesNotMatch(read("../src/features/digest/DigestCard.jsx"), /dangerouslySetInnerHTML/);
console.log("Digest checks passed.");
