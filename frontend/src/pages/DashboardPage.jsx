import { useEffect, useState } from "react";
import { DIAGRAMS_REFRESH_EVENT, json, request } from "../api.js";
import { Sidebar, TopBar } from "../components/index.jsx";

export function Dashboard({ currentUser, onOpen, onLogout, theme, onThemeToggle }) {
  const [boards, setBoards] = useState([]), [title, setTitle] = useState(""), [error, setError] = useState("");
  async function load() { setBoards(await request("/diagrams")); }
  useEffect(() => {
    load().catch((e) => setError(e.message));
    const refresh = () => load().catch((e) => setError(e.message));
    addEventListener(DIAGRAMS_REFRESH_EVENT, refresh);
    return () => removeEventListener(DIAGRAMS_REFRESH_EVENT, refresh);
  }, []);
  async function create(e) {
    e.preventDefault();
    if (!title.trim()) return;
    try {
      const board = await request("/diagrams", json("POST", { title }));
      setTitle(""); await load(); onOpen(board.id);
    } catch (e) { setError(e.message); }
  }
  async function remove(id) {
    if (!window.confirm("¿Eliminar esta pizarra? Esta acción no se puede deshacer.")) return;
    await request(`/diagrams/${id}`, { method: "DELETE" });
    setBoards((current) => current.filter((b) => b.id !== id));
  }
  return <div className="app-shell dashboard">
    <Sidebar currentUser={currentUser} onLogout={onLogout} />
    <div className="app-content"><TopBar theme={theme} onThemeToggle={onThemeToggle} /><main>
      <div className="dash-heading"><div><p className="eyebrow">SU ESPACIO DE TRABAJO</p><h2>Proyectos</h2><p className="muted">Seleccione un proyecto para continuar el modelado o comience con un lienzo nuevo.</p></div>
        <form className="create-form" onSubmit={create}><input aria-label="Título del proyecto" placeholder="Título del nuevo proyecto" value={title} onChange={(e) => setTitle(e.target.value)} /><button>Crear proyecto</button></form>
      </div>
      {error && <p className="error">{error}</p>}
      {boards.length ? <div className="board-grid">{boards.map((b) => <article className="board" key={b.id}><div className="board-mark">⌘</div><h3>{b.title}</h3><p className="muted">{b.is_owner ? "Propietario" : `Miembro · ${b.member_role}`} · Actualizado {b.updated_at ? new Date(b.updated_at).toLocaleDateString() : "recientemente"}</p><div><button onClick={() => onOpen(b.id)}>Abrir proyecto</button>{b.is_owner && <button className="ghost danger-text" onClick={() => remove(b.id)}>Eliminar</button>}</div></article>)}</div> : <div className="empty-board"><b>Aún no hay proyectos</b><span>Cree su primer proyecto arriba para comenzar.</span></div>}
    </main></div>
  </div>;
}
