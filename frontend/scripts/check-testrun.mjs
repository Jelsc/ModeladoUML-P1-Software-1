import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { branchMarks, deploymentNote, endpointStatus, formatMs, groupByEndpoint, hasMutatingCases, outcomeIcon, panelSummary, resultsFor, runSummaryText, statusOf } from "../src/features/chat/testrun-model.js";

const ep = (name, cls = "Account") => ({ class_name: cls, name });
const res = (name, branch, outcome, extra = {}) => ({ case_id: `Account.${name}:${branch}`, endpoint: ep(name), branch, title: branch, method: "GET", path: "/x", status: 200, ms: 12, outcome, detail: "ok", warning: null, ...extra });

// summary text
assert.equal(runSummaryText(null), "Sin pruebas ejecutadas");
assert.equal(runSummaryText({ summary: { passed: 9, failed: 0, skipped: 0, total: 9 } }), "9 de 9 pasaron");
assert.equal(runSummaryText({ summary: { passed: 7, failed: 1, skipped: 1, total: 9 } }), "7 de 9 pasaron · 1 falló · 1 omitida");
assert.equal(runSummaryText({ summary: { passed: 5, failed: 3, skipped: 2, total: 10 } }), "5 de 10 pasaron · 3 fallaron · 2 omitidas");

// overall status: one failure makes the endpoint failed; only skipped means not really tested
assert.equal(statusOf([]), null); assert.equal(statusOf([{ outcome: "passed" }, { outcome: "skipped" }]), "passed");
assert.equal(statusOf([{ outcome: "passed" }, { outcome: "failed" }]), "failed"); assert.equal(statusOf([{ outcome: "skipped" }]), "skipped");
assert.deepEqual(["passed", "failed", "skipped", "x"].map(outcomeIcon), ["✓", "✗", "–", "?"]);

// grouping keeps the order the cases ran and gives each endpoint its status
const run = { results: [res("findByNumber", "ok", "passed"), res("sumPrice", "ok", "passed"), res("findByNumber", "bad_request", "failed"), res("activar", "ok", "skipped")] };
const groups = groupByEndpoint(run.results);
assert.deepEqual(groups.map((g) => [g.label, g.status, g.results.length]), [["Account.findByNumber", "failed", 2], ["Account.sumPrice", "passed", 1], ["Account.activar", "skipped", 1]]);
assert.equal(resultsFor(run, ep("findByNumber")).length, 2); assert.equal(endpointStatus(run, ep("sumPrice")), "passed"); assert.equal(endpointStatus(run, ep("nope")), null); assert.equal(endpointStatus(null, ep("x")), null);

// what the panel says about the deployment
assert.match(deploymentNote(null), /Cargando/);
assert.match(deploymentNote({ deployment: { status: null }, cases: [] }), /Todavía no hay un despliegue/);
assert.match(deploymentNote({ deployment: { status: "failed", running: false }, cases: [] }), /no está en ejecución \(estado: failed\)/);
assert.match(deploymentNote({ deployment: { status: "running", running: true }, cases: [] }), /todavía no tiene endpoints de la IA/);
assert.match(deploymentNote({ deployment: { status: "running", running: true }, cases: [{ endpoint: ep("a") }, { endpoint: ep("a") }, { endpoint: ep("b") }] }), /3 casos de prueba para 2 endpoint/);
assert.equal(panelSummary(null), "Pruebas de la API desplegada"); assert.equal(panelSummary({ deployment: { running: false } }), "Pruebas · API sin desplegar");
assert.equal(panelSummary({ deployment: { running: true }, latest: null }), "Pruebas · todavía sin ejecutar");
assert.equal(panelSummary({ deployment: { running: true }, latest: { summary: { passed: 2, failed: 0, skipped: 0, total: 2 } } }), "Última prueba: 2 de 2 pasaron");

// marks on the life-cycle diagram: the happy case marks the first branch, "no existe" marks the missing-record branch, skipped marks nothing
const flow = { steps: [{ kind: "message" }, { kind: "alt", branches: [{ label: "existe", steps: [] }, { label: "no existe", steps: [] }] }] };
assert.deepEqual(branchMarks(flow, [res("a", "ok", "passed"), res("a", "not_found", "failed")]), { existe: "passed", "no existe": "failed" });
assert.deepEqual(branchMarks(flow, [res("a", "ok", "skipped"), res("a", "not_found", "passed")]), { "no existe": "passed" });
assert.deepEqual(branchMarks({ steps: [{ kind: "message" }] }, [res("a", "ok", "passed")]), {}); assert.deepEqual(branchMarks(flow, []), {});
assert.equal(formatMs(null), ""); assert.equal(formatMs(250), "250 ms"); assert.equal(formatMs(1500), "1.5 s");
assert.equal(hasMutatingCases({ cases: [{ endpoint: ep("activar"), mutating: true }, { endpoint: ep("buscar"), mutating: false }] }, ep("activar")), true);
assert.equal(hasMutatingCases({ cases: [{ endpoint: ep("buscar"), mutating: false }] }, ep("buscar")), false);

// wiring (source checks, like the other feature checks)
const source = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), "utf8");
const panel = source("features/chat/ChatPanel.jsx"), board = source("pages/board-canvas.jsx"), hook = source("features/chat/useTestRuns.js"), view = source("features/chat/TestPanel.jsx"), modal = source("features/chat/MethodFlowModal.jsx"), css = source("style.css");
assert.match(panel, /current\.id === "test" && tests && <TestPanel/, "the Probar panel lives in the Test chat only");
assert.equal((panel.match(/<TestPanel/g) || []).length, 1);
assert.match(board, /useTestRuns\(\{ diagramId: id, subscribe: collaboration\.subscribe \}\)/); assert.match(board, /<MethodFlowModal endpoint=\{flowTarget\}.*?tests=\{tests\}/); assert.match(board, /proposals\.dismissError \}\} tests=\{tests\}/);
assert.match(hook, /ai\.testrun/); assert.match(hook, /\/tests\/run/); assert.match(hook, /include_mutating: includeMutating, endpoint/);
assert.match(view, /window\.confirm\(/, "tests that change data ask for confirmation"); assert.match(view, /data\?\.can_run_mutating &&/, "only editors see the mutating option");
assert.match(view, /disabled=\{!data\?\.can_run \|\| running/);
assert.match(modal, /Probar este endpoint/); assert.match(modal, /marks=\{branchMarks\(flow, results\)\}/); assert.match(modal, /useMethodFlow\(endpoint\.id, tests\?\.data\?\.latest\?\.id\)/);
assert.match(css, /\.flow-mark\.failed/); assert.match(css, /\.board-test-icon\.passed/);

console.log("testrun check ok");
