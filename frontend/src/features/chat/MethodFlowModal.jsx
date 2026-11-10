import { useEffect, useRef, useState } from "react";
import { accessLabel, clip, flowOutline, layoutFlow, relationLabel } from "./flow-model.js";
import { kindLabel, statusLabel } from "./endpoint-model.js";
import { useMethodFlow } from "./useMethodFlow.js";

export function FlowSvg({ flow }) {
  const view = layoutFlow(flow);
  return <svg className="method-flow-svg" width={view.width} height={view.height} viewBox={`0 0 ${view.width} ${view.height}`} role="img" aria-label={`Diagrama de secuencia de ${flow.title}`}>
    <defs>
      <marker id="flow-arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto" markerUnits="userSpaceOnUse"><path d="M0 0 L9 4.5 L0 9 Z" className="flow-arrowhead" /></marker>
    </defs>
    {view.lifelines.map((line) => <line key={line.x} className="flow-lifeline" x1={line.x} x2={line.x} y1={line.y1} y2={line.y2} />)}
    {view.boxes.map((box, index) => <g key={`box-${index}`} className={`flow-box ${box.tag}`}>
      <rect x={box.x} y={box.y} width={box.w} height={box.h} rx="4" />
      <path className="flow-tab" d={`M${box.x} ${box.y} h${box.tag === "alt" ? 36 : 52} v16 l-8 8 h-${box.tag === "alt" ? 28 : 44} z`} />
      <text className="flow-tab-text" x={box.x + 6} y={box.y + 16}>{box.tag}</text>
      <text className="flow-condition" x={box.x + (box.tag === "alt" ? 46 : 62)} y={box.y + 17}>[{clip(box.label, 52)}]<title>{box.label}</title></text>
    </g>)}
    {view.dividers.map((divider, index) => <g key={`div-${index}`}><line className="flow-divider" x1={divider.x1} x2={divider.x2} y1={divider.y} y2={divider.y} /><text className="flow-condition" x={divider.x1 + 10} y={divider.y + 17}>[{clip(divider.label, 52)}]<title>{divider.label}</title></text></g>)}
    {view.participants.map((p) => <g key={p.id} className={`flow-participant ${p.id}`}><rect x={p.x - 74} y="8" width="148" height="30" rx="6" /><text x={p.x} y="28" textAnchor="middle">{clip(p.label, 20)}<title>{p.label}</title></text></g>)}
    {view.arrows.map((arrow, index) => <g key={`a-${index}`} className="flow-arrow">
      <line className={arrow.dashed ? "flow-return" : "flow-call"} x1={arrow.x1} x2={arrow.x2 + (arrow.direction === "right" ? -2 : 2)} y1={arrow.y} y2={arrow.y} markerEnd="url(#flow-arrow)" />
      <text className="flow-label" x={arrow.labelX} y={arrow.y - 7} textAnchor="middle">{clip(arrow.label)}<title>{arrow.label}</title></text>
    </g>)}
    {view.selfs.map((item, index) => <g key={`s-${index}`} className={`flow-self${item.note ? " note" : ""}`}>
      <path className="flow-call" d={`M${item.x} ${item.y - 18} h34 v20 h-32`} markerEnd="url(#flow-arrow)" fill="none" />
      <text className="flow-label" x={item.x + 42} y={item.y - 4}>{clip(item.label, 44)}<title>{item.label}</title></text>
    </g>)}
  </svg>;
}

function Section({ title, empty, children }) {
  return <section className="method-flow-section"><h3>{title}</h3>{children || <p className="muted">{empty}</p>}</section>;
}

// Opened with a double click on an endpoint: the whole path of the method and everything it is connected to.
export function MethodFlowModal({ endpoint, onClose }) {
  const { flow, loading, error } = useMethodFlow(endpoint.id);
  const [copied, setCopied] = useState(""), closeRef = useRef(null);
  useEffect(() => { closeRef.current?.focus(); }, []);
  useEffect(() => { const onKey = (event) => { if (event.key === "Escape") { event.stopPropagation(); onClose(); } }; addEventListener("keydown", onKey, true); return () => removeEventListener("keydown", onKey, true); }, [onClose]);
  const copy = async () => {
    try { await navigator.clipboard.writeText(flow.mermaid); setCopied("Copiado: pegalo en un README, GitHub, Notion o mermaid.live"); }
    catch { setCopied("No pude copiar automáticamente: abrí «Ver texto» y copialo a mano"); }
  };
  return <div className="modal-backdrop method-flow-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className="method-flow-modal" role="dialog" aria-modal="true" aria-labelledby="method-flow-title">
      <div className="modal-heading"><div><p className="eyebrow">CICLO DE VIDA DEL MÉTODO</p><h2 id="method-flow-title">{flow?.title || `${endpoint.http_method} ${endpoint.route}`}</h2>
        <p className="muted">{endpoint.class_name}.{endpoint.name} · {kindLabel(endpoint.kind)} · <span className={`board-endpoint-status ${endpoint.status}`}>{statusLabel(endpoint.status)}</span>{endpoint.status !== "approved" && " (todavía no se despliega)"}</p></div>
        <button ref={closeRef} type="button" className="ghost" onClick={onClose} aria-label="Cerrar el diagrama">×</button></div>
      {loading && <p role="status">Armando el diagrama…</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {flow && <>
        {flow.description && <p className="method-flow-description">{flow.description}</p>}
        {flow.warnings.length > 0 && <ul className="method-flow-warnings" role="note">{flow.warnings.map((warning) => <li key={warning}>⚠ {warning}</li>)}</ul>}
        <div className="method-flow-scroll" tabIndex={0} aria-label="Diagrama de secuencia (desplazable)"><FlowSvg flow={flow} /></div>
        <div className="method-flow-columns">
          <Section title="Depende de" empty="No llama a otros métodos: solo usa su repositorio.">{flow.calls.length > 0 && <ul>{flow.calls.map((call) => <li key={call.name}><b>{call.name}</b> <span className="muted">{call.kind === "crud" ? "CRUD generado" : "otro endpoint"} · {call.reason}</span></li>)}</ul>}</Section>
          <Section title="Lo usan" empty="Ningún otro método lo llama.">{flow.used_by.length > 0 && <ul>{flow.used_by.map((user) => <li key={user.name}><b>{user.name}</b> <span className="muted">{user.reason}</span></li>)}</ul>}</Section>
          <Section title="Datos que toca" empty="">{<ul>{flow.touches.map((touch) => <li key={touch.class}><b>{touch.class}</b> <span className="muted">{accessLabel(touch.access)} · {touch.detail}</span></li>)}{flow.related.map((relation) => <li key={relationLabel(relation)}><span className="muted">Relacionada: {relationLabel(relation)}</span></li>)}</ul>}</Section>
        </div>
        <Section title="Casos de prueba sugeridos (uno por rama)" empty=""><div className="method-flow-tests">{flow.tests.map((test) => <article key={test.title}><b>{test.title}</b>{test.given && <p><span>Dado</span> {test.given}</p>}<p><span>Cuando</span> <code>{test.request}</code></p><p><span>Entonces</span> {test.expect}</p></article>)}</div></Section>
        <details className="method-flow-text"><summary>Ver texto (Mermaid y esquema)</summary><textarea readOnly rows={8} value={flow.mermaid} aria-label="Diagrama en formato Mermaid" /><pre>{flowOutline(flow)}</pre></details>
        <div className="form-actions"><button type="button" onClick={copy}>Copiar Mermaid</button><button type="button" className="ghost" onClick={onClose}>Cerrar</button></div>
        {copied && <p className="muted" role="status">{copied}</p>}
      </>}
    </section>
  </div>;
}
