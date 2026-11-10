// Pure helpers for the "Probar" feature of the Test chat: results of running the test cases against the deployed API (no React, no DOM).
export const OUTCOME_ICON = { passed: "✓", failed: "✗", skipped: "–" };
export const OUTCOME_LABEL = { passed: "Pasó", failed: "Falló", skipped: "Omitida" };
export const outcomeIcon = (outcome) => OUTCOME_ICON[outcome] || "?";
export const outcomeLabel = (outcome) => OUTCOME_LABEL[outcome] || outcome;
export const endpointLabel = (endpoint) => `${endpoint?.class_name ?? "?"}.${endpoint?.name ?? "?"}`;

const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;

// "7 de 9 pasaron · 1 falló · 1 omitida"
export function runSummaryText(run) {
  const summary = run?.summary;
  if (!summary) return "Sin pruebas ejecutadas";
  const parts = [`${summary.passed} de ${summary.total} pasaron`];
  if (summary.failed) parts.push(summary.failed === 1 ? "1 falló" : `${summary.failed} fallaron`);
  if (summary.skipped) parts.push(plural(summary.skipped, "omitida", "omitidas"));
  return parts.join(" · ");
}

// failed wins over passed (one broken case makes the endpoint "failed"); only skipped cases mean "not really tested".
export function statusOf(results) {
  if (!results?.length) return null;
  if (results.some((item) => item.outcome === "failed")) return "failed";
  if (results.some((item) => item.outcome === "passed")) return "passed";
  return "skipped";
}

export const resultsFor = (run, endpoint) => (run?.results || []).filter((item) => item.endpoint?.class_name === endpoint?.class_name && item.endpoint?.name === endpoint?.name);
export const endpointStatus = (run, endpoint) => statusOf(resultsFor(run, endpoint));

// Results grouped by endpoint, in the order they ran, each with its overall status.
export function groupByEndpoint(results) {
  const groups = new Map();
  for (const item of results || []) {
    const key = endpointLabel(item.endpoint);
    if (!groups.has(key)) groups.set(key, { key, label: key, results: [] });
    groups.get(key).results.push(item);
  }
  return [...groups.values()].map((group) => ({ ...group, status: statusOf(group.results) }));
}

// What the panel says about the deployment it would test.
export function deploymentNote(data) {
  if (!data) return "Cargando…";
  const deployment = data.deployment || {};
  if (!deployment.status) return "Todavía no hay un despliegue. Despliegue el proyecto desde el botón Desplegar para poder probarlo.";
  if (!deployment.running) return `El despliegue no está en ejecución (estado: ${deployment.status}). Despliegue de nuevo para poder probarlo.`;
  if (!data.cases?.length) return "La API está en ejecución, pero todavía no tiene endpoints de la IA desplegados para probar.";
  return `La API está en ejecución. Hay ${plural(data.cases.length, "caso", "casos")} de prueba para ${new Set(data.cases.map((item) => endpointLabel(item.endpoint))).size} endpoint(s).`;
}

export function panelSummary(data) {
  if (!data) return "Pruebas de la API desplegada";
  if (!data.deployment?.running) return "Pruebas · API sin desplegar";
  return data.latest ? `Última prueba: ${runSummaryText(data.latest)}` : "Pruebas · todavía sin ejecutar";
}

// Marks for the branches (alt boxes) of a life-cycle diagram: the happy case marks the first branch, "registro que no existe" the branch about a missing record.
export function branchMarks(flow, results) {
  const alt = (flow?.steps || []).find((step) => step.kind === "alt");
  if (!alt || !results?.length) return {};
  const happy = results.find((item) => item.branch === "ok"), missing = results.find((item) => item.branch === "not_found"), marks = {};
  alt.branches.forEach((branch, index) => {
    const result = /no existe|no encontr|inexistent/i.test(branch.label) ? missing : index === 0 ? happy : null;
    if (result && result.outcome !== "skipped") marks[branch.label] = result.outcome;
  });
  return marks;
}

export const formatMs = (ms) => (ms == null ? "" : ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`);

// Whether a case of this endpoint changes data (needs the confirmation checkbox).
export const hasMutatingCases = (data, endpoint) => (data?.cases || []).some((item) => item.mutating && item.endpoint?.class_name === endpoint?.class_name && item.endpoint?.name === endpoint?.name);
