import { useState } from "react";
import { deploymentNote, formatMs, groupByEndpoint, outcomeIcon, outcomeLabel, panelSummary, runSummaryText } from "./testrun-model.js";

// One line per executed case: ✓/✗/–, what was tried, the HTTP status, the time and why it passed or failed.
export function ResultList({ results }) {
  return <ul>{results.map((result) => <li key={result.case_id} className={`board-test-result ${result.outcome}`}>
    <span className={`board-test-icon ${result.outcome}`} aria-label={outcomeLabel(result.outcome)}>{outcomeIcon(result.outcome)}</span>
    <span className="board-test-title">{result.title}</span>
    <code title={result.path}>{result.method} {result.status ?? "—"}</code>
    {result.ms != null && <small>{formatMs(result.ms)}</small>}
    <p>{result.detail}{result.warning && <span className="board-test-warning"> ⚠ {result.warning}</span>}</p>
  </li>)}</ul>;
}

// "Probar" in the Test chat: runs the test cases against the deployed API and shows what really happened.
export function TestPanel({ data, running, error, onRun, onRefresh, onDismissError }) {
  const [mutating, setMutating] = useState(false);
  const latest = data?.latest, groups = groupByEndpoint(latest?.results);
  const start = () => {
    if (mutating && !window.confirm("Estas pruebas pueden MODIFICAR registros existentes del despliegue (por ejemplo, activar o cambiar un dato). ¿Continuar?")) return;
    onRun({ includeMutating: mutating });
  };
  return <details className="board-tests" open>
    <summary>{panelSummary(data)}</summary>
    <p className="board-tests-note">{deploymentNote(data)}</p>
    <div className="board-tests-actions">
      <button type="button" disabled={!data?.can_run || running || !data?.cases?.length} onClick={start}>{running ? "Probando…" : "Probar"}</button>
      <button type="button" className="ghost" disabled={running} onClick={onRefresh}>Actualizar estado</button>
      {data?.can_run_mutating && <label className="board-tests-mutating"><input type="checkbox" checked={mutating} disabled={running} onChange={(event) => setMutating(event.target.checked)} /> Incluir pruebas que modifican datos</label>}
    </div>
    {latest && <p className="board-tests-last">Última prueba: <b>{runSummaryText(latest)}</b>{latest.requested_by ? ` · por ${latest.requested_by}` : ""}</p>}
    <ul className="board-tests-groups">{groups.map((group) => <li key={group.key} className={`board-test-group ${group.status}`}>
      <div className="board-test-group-head"><span className={`board-test-icon ${group.status}`} aria-label={outcomeLabel(group.status)}>{outcomeIcon(group.status)}</span><b>{group.label}</b></div>
      <ResultList results={group.results} />
    </li>)}</ul>
    {error && <p className="error board-chat-error" role="alert">{error} <button type="button" className="ghost" onClick={onDismissError}>Ocultar</button></p>}
  </details>;
}
