import { useEffect, useState } from "react";
import { json, request } from "../api.js";
import { Sidebar, TopBar } from "../components/index.jsx";

const emptyUser = { email: "", name: "", password: "", role: "viewer", active: true };

export function UserManagement({ onLogout }) {
  const [users, setUsers] = useState([]), [form, setForm] = useState(emptyUser), [editing, setEditing] = useState(null), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const load = async () => setUsers(await request("/admin/users"));
  useEffect(() => { load().catch((e) => e.status === 401 ? onLogout() : setError(e.message)); }, []);
  const set = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  const reset = () => { setEditing(null); setForm(emptyUser); };
  async function save(e) {
    e.preventDefault(); setError(""); setNotice(""); const payload = { ...form };
    if (editing && !payload.password) delete payload.password;
    try { await request(editing ? `/admin/users/${editing.id}` : "/admin/users", json(editing ? "PATCH" : "POST", payload)); reset(); await load(); setNotice(editing ? "Usuario actualizado." : "Usuario creado."); }
    catch (e) { if (e.status === 401) onLogout(); else if (e.status === 403) setError("No tiene autorización para administrar usuarios."); else setError(e.message); }
  }
  async function remove(item) {
    if (!window.confirm(`¿Eliminar a ${item.name}? Esta acción no se puede deshacer.`)) return;
    try { await request(`/admin/users/${item.id}`, { method: "DELETE" }); await load(); setNotice("Usuario eliminado."); }
    catch (e) { if (e.status === 401) onLogout(); else setError(e.status === 403 ? "No tiene autorización para administrar usuarios." : e.message); }
  }
  function edit(item) { setEditing(item); setForm({ email: item.email, name: item.name, password: "", role: item.role, active: item.active }); setError(""); setNotice(""); }
  return <section className="user-management"><div className="section-heading"><div><p className="eyebrow">ADMINISTRACIÓN</p><h2>Usuarios</h2><p className="muted">Gestione accesos, roles y estado de las cuentas.</p></div><span className="admin-badge">Solo administradores</span></div>
    <div className="user-layout"><UserForm form={form} editing={editing} set={set} save={save} reset={reset} /><UserTable users={users} edit={edit} remove={remove} /></div>
    {(error || notice) && <p className={error ? "error" : "notice"}>{error || notice}</p>}
  </section>;
}

function UserForm({ form, editing, set, save, reset }) { return <form className="user-form" onSubmit={save}><h3>{editing ? "Editar usuario" : "Nuevo usuario"}</h3><label>Nombre<input required value={form.name} onChange={(e) => set("name", e.target.value)} /></label><label>Correo electrónico<input required type="email" value={form.email} onChange={(e) => set("email", e.target.value)} /></label><label>Contraseña{editing && <small className="field-hint">Déjela vacía para conservarla.</small>}<input required={!editing} type="password" minLength="8" value={form.password} onChange={(e) => set("password", e.target.value)} /></label><label>Rol<select value={form.role} onChange={(e) => set("role", e.target.value)}><option value="admin">Administrador</option><option value="editor">Editor</option><option value="viewer">Viewer</option></select></label><label className="checkbox"><input type="checkbox" checked={form.active} onChange={(e) => set("active", e.target.checked)} /> Cuenta activa</label><div className="form-actions"><button>{editing ? "Guardar cambios" : "Crear usuario"}</button>{editing && <button type="button" className="ghost" onClick={reset}>Cancelar</button>}</div></form>; }

function UserTable({ users, edit, remove }) { return <div className="user-list">{users.length ? <div className="user-table" role="table"><div className="user-row user-row-head" role="row"><span>Usuario</span><span>Rol</span><span>Estado</span><span>Acciones</span></div>{users.map((item) => <div className="user-row" role="row" key={item.id}><div><b>{item.name}</b><small>{item.email}</small></div><span className="role-pill">{item.role}</span><span className={item.active ? "status-active" : "status-inactive"}>{item.active ? "Activo" : "Inactivo"}</span><div className="row-actions"><button className="ghost" onClick={() => edit(item)}>Editar</button><button className="ghost danger-text" onClick={() => remove(item)}>Eliminar</button></div></div>)}</div> : <div className="empty-board">No hay usuarios registrados.</div>}</div>; }

export function UserManagementPage({ currentUser, onLogout, theme, onThemeToggle }) { return <div className="app-shell user-page"><Sidebar currentUser={currentUser} onLogout={onLogout} /><div className="app-content"><TopBar theme={theme} onThemeToggle={onThemeToggle} /><main><UserManagement currentUser={currentUser} onLogout={onLogout} /></main></div></div>; }
