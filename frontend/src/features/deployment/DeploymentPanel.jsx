import { useEffect, useRef, useState } from "react";
import { request } from "../../api.js";

const BUSY_STATUSES = ["queued", "building", "starting"];

function CredentialsDialog({ diagramId, onClose }) {
  const dialogRef = useRef(null);
  const [credentials, setCredentials] = useState(null);
  const [error, setError] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [copied, setCopied] = useState("");

  useEffect(() => {
    let active = true;
    request(`/diagrams/${diagramId}/deployment/credentials`)
      .then((value) => active && setCredentials(value))
      .catch((reason) => active && setError(reason.message));
    dialogRef.current?.querySelector("button")?.focus();
    return () => { active = false; };
  }, [diagramId]);

  const onKeyDown = (event) => {
    if (event.key === "Escape") { event.stopPropagation(); onClose(); return; }
    if (event.key !== "Tab") return;
    const focusable = [...dialogRef.current.querySelectorAll("button:not(:disabled)")];
    if (!focusable.length) return;
    const first = focusable[0], last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };
  const copy = async (label, value) => {
    try {
      await navigator.clipboard.writeText(String(value));
      setCopied(`${label} copiado`);
    } catch {
      setCopied(`No se pudo copiar ${label.toLowerCase()}`);
    }
  };
  const fields = credentials ? [
    ["Host", credentials.host],
    ["Puerto", credentials.port],
    ["Base de datos", credentials.database],
    ["Usuario", credentials.username],
    ["JDBC URL", credentials.jdbc_url],
  ] : [];
  const maskedUri = credentials?.postgresql_uri.replace(credentials.password, "••••••••••••••••");

  return <div className="modal-backdrop credentials-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section ref={dialogRef} className="credentials-modal" role="dialog" aria-modal="true" aria-labelledby="credentials-title" aria-describedby="credentials-description" onKeyDown={onKeyDown}>
      <div className="modal-heading"><div><p className="eyebrow">POSTGRESQL LOCAL</p><h2 id="credentials-title">Conexión a base de datos</h2></div><button type="button" className="ghost" onClick={onClose} aria-label="Cerrar credenciales">×</button></div>
      <p id="credentials-description" className="field-hint">Disponible únicamente desde esta máquina mientras el despliegue esté activo.</p>
      {!credentials && !error && <p className="credentials-loading" role="status">Verificando puerto y credenciales…</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {credentials && <dl className="credentials-list">
        {fields.map(([label, value]) => <div className="credential-row" key={label}><dt>{label}</dt><dd><code>{value}</code><button type="button" className="ghost credential-copy" onClick={() => copy(label, value)} aria-label={`Copiar ${label}`}>Copiar</button></dd></div>)}
        <div className="credential-row"><dt>PostgreSQL URI</dt><dd><code>{showPassword ? credentials.postgresql_uri : maskedUri}</code><button type="button" className="ghost credential-copy" onClick={() => copy("PostgreSQL URI", credentials.postgresql_uri)}>Copiar</button></dd></div>
        <div className="credential-row"><dt>Contraseña</dt><dd><code>{showPassword ? credentials.password : "••••••••••••••••"}</code><div className="credential-controls"><button type="button" className="ghost credential-copy" aria-pressed={showPassword} onClick={() => setShowPassword((value) => !value)}>{showPassword ? "Ocultar" : "Mostrar"}</button><button type="button" className="ghost credential-copy" onClick={() => copy("Contraseña", credentials.password)}>Copiar</button></div></dd></div>
      </dl>}
      <p className="copy-feedback" aria-live="polite">{copied}</p>
    </section>
  </div>;
}

export function DeploymentPanel({ diagramId, onClose }) {
  const credentialsTrigger = useRef(null);
  const [deployment, setDeployment] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [credentialsOpen, setCredentialsOpen] = useState(false);
  const load = () => request(`/diagrams/${diagramId}/deployment`).then(setDeployment).catch((reason) => setError(reason.message));
  useEffect(() => { load(); }, [diagramId]);
  useEffect(() => { if (!deployment || !BUSY_STATUSES.includes(deployment.status)) return undefined; const timer = setInterval(load, 3000); return () => clearInterval(timer); }, [deployment?.status, diagramId]);
  const action = async (method) => { setBusy(true); setError(""); try { await request(`/diagrams/${diagramId}/deployment`, { method }); await load(); } catch (reason) { setError(reason.message); } finally { setBusy(false); } };
  const closeCredentials = () => { setCredentialsOpen(false); requestAnimationFrame(() => credentialsTrigger.current?.focus()); };
  const downloadPostman = async () => {
    setError("");
    try {
      const collection = await request(`/diagrams/${diagramId}/deployment/postman`);
      const url = URL.createObjectURL(new Blob([JSON.stringify(collection, null, 2)], { type: "application/json" }));
      try {
        const link = document.createElement("a");
        link.href = url;
        link.download = `${deployment.slug}.postman_collection.json`;
        document.body.appendChild(link);
        link.click();
        link.remove();
      } finally {
        URL.revokeObjectURL(url);
      }
    } catch (reason) { setError(reason.message); }
  };
  const status = deployment?.status || "stopped", running = status === "running";

  return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="deployment-modal" role="dialog" aria-modal="true" aria-hidden={credentialsOpen || undefined} inert={credentialsOpen ? true : undefined} aria-labelledby="deployment-title">
    <div className="modal-heading"><div><p className="eyebrow">LOCAL MVP</p><h2 id="deployment-title">Backend desplegado</h2></div><button type="button" className="ghost" onClick={onClose} aria-label="Cerrar">×</button></div>
    <p className={`deployment-status deployment-${status}`}>{status}</p>
    {deployment?.url && <p className="deployment-url"><b>URL de la API</b><br /><code>{deployment.url}</code></p>}
    {deployment?.error_summary && <p className="error" role="alert"><b>Diagnóstico del fallo:</b><br />{deployment.error_summary}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    <small className="field-hint">El despliegue usa contenedores Spring y PostgreSQL aislados. Detener o reconstruir elimina su volumen de datos.</small>
    <div className="deployment-actions"><button disabled={busy || BUSY_STATUSES.includes(status)} onClick={() => action("POST")}>Desplegar / reconstruir</button>{running && <button className="ghost" onClick={() => window.open(deployment.url, "_blank", "noopener,noreferrer")}>Abrir API</button>}</div>
    {running && <section className="deployment-integrations" aria-labelledby="deployment-integrations-title"><div><p className="eyebrow" id="deployment-integrations-title">INTEGRACIONES</p><small>Conectá herramientas locales al entorno desplegado.</small></div><div className="integration-actions"><button ref={credentialsTrigger} type="button" className="ghost" onClick={() => setCredentialsOpen(true)}>Conexión a base de datos</button><button type="button" className="ghost" onClick={downloadPostman}>Descargar colección Postman</button></div></section>}
    <div className="deployment-danger"><button className="ghost danger-text" disabled={busy || status === "stopped"} onClick={() => action("DELETE")}>Detener despliegue</button></div>
  </section>{credentialsOpen && <CredentialsDialog diagramId={diagramId} onClose={closeCredentials} />}</div>;
}
