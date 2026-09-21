import { useEffect, useRef, useState } from "react";
import { applyPhotoProposal, detectFromPhoto } from "./vision.js";

export const PHOTO_IMPORT_STATES = { PICK: "PICK", REVIEW: "REVIEW", APPLYING: "APPLYING" };

function selectedCount(proposal) {
  return proposal.classes.filter((item) => item.selected).length;
}

export function ImportFromPhotoModal({ onClose, onApplied }) {
  const [state, setState] = useState(PHOTO_IMPORT_STATES.PICK);
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState("");
  const [proposal, setProposal] = useState(null);
  const [error, setError] = useState("");
  const dialogRef = useRef(null);
  const previousFocus = useRef(document.activeElement);
  const inputRef = useRef(null);

  useEffect(() => {
    const url = file ? URL.createObjectURL(file) : "";
    setPreviewUrl(url);
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [file]);
  useEffect(() => {
    previousFocus.current = document.activeElement;
    dialogRef.current?.querySelector("button, input")?.focus();
    return () => requestAnimationFrame(() => previousFocus.current?.focus?.());
  }, []);
  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === "Escape" && state !== PHOTO_IMPORT_STATES.APPLYING) onClose();
    };
    addEventListener("keydown", onKeyDown);
    return () => removeEventListener("keydown", onKeyDown);
  }, [onClose, state]);

  function choose(nextFile) {
    setError("");
    setFile(nextFile || null);
    setProposal(null);
    setState(PHOTO_IMPORT_STATES.PICK);
  }
  async function analyze() {
    if (!file) return;
    setError(""); setState("ANALYZING");
    try { setProposal(await detectFromPhoto(file)); setState(PHOTO_IMPORT_STATES.REVIEW); }
    catch (cause) { setError(cause.message); setState(PHOTO_IMPORT_STATES.PICK); }
  }
  function setClassSelected(classId, selected) {
    setProposal((current) => ({ ...current, classes: current.classes.map((item) => item.id === classId ? { ...item, selected, attributes: item.attributes.map((x) => ({ ...x, selected })), methods: item.methods.map((x) => ({ ...x, selected })) } : item), relations: current.relations.map((item) => item.source_id === classId || item.target_id === classId ? { ...item, selected: selected ? item.selected : false } : item) }));
  }
  function setChildSelected(classId, kind, itemId, selected) {
    setProposal((current) => ({ ...current, classes: current.classes.map((item) => item.id === classId ? { ...item, [kind]: item[kind].map((child) => child.id === itemId ? { ...child, selected } : child) } : item) }));
  }
  function setRelationSelected(relationId, selected) { setProposal((current) => ({ ...current, relations: current.relations.map((item) => item.id === relationId ? { ...item, selected } : item) })); }
  async function apply() {
    if (!proposal || !selectedCount(proposal)) return;
    setError(""); setState(PHOTO_IMPORT_STATES.APPLYING);
    try { const result = await applyPhotoProposal(proposal); onApplied(result.diagram); }
    catch (cause) { setError(cause.message); setState(PHOTO_IMPORT_STATES.REVIEW); }
  }
  return <div className="modal-backdrop photo-import-backdrop" onMouseDown={(event) => event.target === event.currentTarget && state !== PHOTO_IMPORT_STATES.APPLYING && onClose()}>
    <section ref={dialogRef} className="photo-import-modal" role="dialog" aria-modal="true" aria-labelledby="photo-import-title">
      <div className="modal-heading"><div><p className="eyebrow">IMPORTACIÓN CONTROLADA</p><h2 id="photo-import-title">Generar desde foto</h2><p className="muted">La imagen se analiza sin crear nada hasta que confirmes la propuesta.</p></div><button type="button" className="ghost" onClick={onClose} disabled={state === PHOTO_IMPORT_STATES.APPLYING} aria-label="Cerrar importación">×</button></div>
      {state === PHOTO_IMPORT_STATES.PICK || state === "ANALYZING" ? <div className="photo-import-pick">
        <label className="photo-dropzone"> <span>{state === "ANALYZING" ? "Analizando diagrama UML..." : "Seleccioná una foto del diagrama"}</span><input ref={inputRef} type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif" onChange={(event) => choose(event.target.files?.[0])} disabled={state === "ANALYZING"} /></label>
        {previewUrl && <img className="photo-preview" src={previewUrl} alt="Vista previa del diagrama seleccionado" />}
        {state === "ANALYZING" && <p className="notice" aria-live="polite">La imagen sigue visible mientras se analiza.</p>}
        <div className="form-actions"><button type="button" onClick={analyze} disabled={!file || state === "ANALYZING"}>{state === "ANALYZING" ? "Analizando..." : "Analizar foto"}</button><button type="button" className="ghost" onClick={onClose} disabled={state === "ANALYZING"}>Cancelar</button></div>
      </div> : <div className="photo-import-review">
        <label>Nombre del proyecto<input value={proposal.project_name} onChange={(event) => setProposal({ ...proposal, project_name: event.target.value })} maxLength={200} /></label>
        <div className="review-summary"><b>{selectedCount(proposal)} clases seleccionadas</b><span>{proposal.relations.filter((item) => item.selected).length} relaciones</span></div>
        <div className="proposal-list">{proposal.classes.map((item) => <fieldset key={item.id} className={!item.selected ? "proposal-item is-disabled" : "proposal-item"}><label className="checkbox"><input type="checkbox" checked={item.selected} onChange={(event) => setClassSelected(item.id, event.target.checked)} /> <strong>{item.name}</strong></label><div className="proposal-children">{item.attributes.map((child) => <label className="checkbox" key={child.id}><input type="checkbox" checked={child.selected} disabled={!item.selected} onChange={(event) => setChildSelected(item.id, "attributes", child.id, event.target.checked)} /> atributo: {child.name}: {child.type}</label>)}{item.methods.map((child) => <label className="checkbox" key={child.id}><input type="checkbox" checked={child.selected} disabled={!item.selected} onChange={(event) => setChildSelected(item.id, "methods", child.id, event.target.checked)} /> método: {child.name}(): {child.return_type}</label>)}</div></fieldset>)}{proposal.relations.map((item) => { const source = proposal.classes.find((x) => x.id === item.source_id); const target = proposal.classes.find((x) => x.id === item.target_id); const endpointsSelected = source?.selected && target?.selected; return <label className="checkbox proposal-relation" key={item.id}><input type="checkbox" checked={item.selected && endpointsSelected} disabled={!endpointsSelected} onChange={(event) => setRelationSelected(item.id, event.target.checked)} /> relación: {source?.name || item.source_id} · {item.type} · {target?.name || item.target_id} · multiplicidades: {item.source_multiplicity || "-"} / {item.target_multiplicity || "-"}{item.label ? ` · ${item.label}` : ""}</label>; })}</div>
        {proposal.warnings?.length > 0 && <div className="xmi-warnings"><strong>Advertencias de análisis</strong><ul>{proposal.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
        {error && <p className="error" role="alert">{error}</p>}<p className="muted">Revisá cada elemento. Solo se aplicará lo seleccionado.</p><div className="form-actions"><button type="button" onClick={apply} disabled={!selectedCount(proposal)}>Crear diagrama revisado</button><button type="button" className="ghost" onClick={onClose}>Cancelar</button></div>
      </div>}
      {error && state !== PHOTO_IMPORT_STATES.REVIEW && <p className="error" role="alert">{error}</p>}
    </section>
  </div>;
}
