import { useEffect, useState } from "react";
import { json, request } from "../../api.js";

export function MembersPanel({ diagramId, onClose }) {
  const [members, setMembers] = useState([]), [email, setEmail] = useState(""), [role, setRole] = useState("editor"), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const load = async () => setMembers(await request(`/diagrams/${diagramId}/members`));
  useEffect(() => { load().catch((e) => setError(e.message)); }, [diagramId]);
  async function add(e) { e.preventDefault(); setError(""); setNotice(""); try { await request(`/diagrams/${diagramId}/members`, json("POST", { email, role })); setEmail(""); setNotice("Miembro agregado al instante."); await load(); } catch (e) { setError(e.message); } }
  async function change(member, nextRole) { try { await request(`/diagrams/${diagramId}/members/${member.id}`, json("PATCH", { role: nextRole })); await load(); } catch (e) { setError(e.message); } }
  async function remove(member) { if (!window.confirm(`¿Quitar a ${member.name} de esta pizarra?`)) return; try { await request(`/diagrams/${diagramId}/members/${member.id}`, { method: "DELETE" }); await load(); } catch (e) { setError(e.message); } }
  return <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}><section className="members-modal" role="dialog" aria-modal="true" aria-labelledby="members-title"><div className="modal-heading"><div><p className="eyebrow">COLABORACIÓN</p><h2 id="members-title">Miembros de la pizarra</h2></div><button type="button" className="ghost" aria-label="Cerrar" onClick={onClose}>×</button></div>
    <form className="member-form" onSubmit={add}><label>Correo de usuario registrado<input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="persona@ejemplo.com" /></label><label>Permiso<select value={role} onChange={(e) => setRole(e.target.value)}><option value="editor">Editor</option><option value="viewer">Viewer</option></select></label><button>Agregar miembro</button></form>
    {error && <p className="error">{error}</p>}{notice && <p className="notice">{notice}</p>}<div className="member-list">{members.map((member) => <div className="member-row" key={member.id}><div><b>{member.name}</b><small>{member.email}</small></div>{member.is_owner ? <span className="role-pill">Propietario</span> : <><select aria-label={`Rol de ${member.name}`} value={member.role} onChange={(e) => change(member, e.target.value)}><option value="editor">Editor</option><option value="viewer">Viewer</option></select><button className="ghost danger-text" onClick={() => remove(member)}>Quitar</button></>}</div>)}</div>
  </section></div>;
}
