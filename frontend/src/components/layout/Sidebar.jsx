import { useEffect, useState } from "react";
import { SidebarIcon } from "../icons/SidebarIcon.jsx";

export function Sidebar({ currentUser, onLogout }) {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("uml-sidebar-collapsed") === "true");
  const [route, setRoute] = useState(() => location.hash);
  useEffect(() => { localStorage.setItem("uml-sidebar-collapsed", String(collapsed)); }, [collapsed]);
  useEffect(() => {
    const update = () => setRoute(location.hash);
    addEventListener("hashchange", update);
    return () => removeEventListener("hashchange", update);
  }, []);
  const admin = currentUser?.role === "admin";
  return <aside className={`sidebar ${collapsed ? "sidebar-collapsed" : ""}`} aria-label="Navegación principal">
    <div className="sidebar-brand"><strong>arc / uml</strong><button type="button" className="ghost sidebar-toggle" onClick={() => setCollapsed((value) => !value)} aria-label={collapsed ? "Expandir navegación" : "Contraer navegación"} title={collapsed ? "Expandir navegación" : "Contraer navegación"}><SidebarIcon name="menu" /></button></div>
    <nav className="sidebar-links">
      <a className={!route.startsWith("#/board") && route !== "#/gestion-usuarios" ? "active" : ""} href="#/dashboard" title="Proyectos"><SidebarIcon name="projects" /><span>Proyectos</span></a>
      {admin && <a className={route === "#/gestion-usuarios" ? "active" : ""} href="#/gestion-usuarios" title="Gestión de usuarios"><SidebarIcon name="users" /><span>Gestión de usuarios</span></a>}
    </nav>
    <button type="button" className="sidebar-logout" onClick={onLogout} title="Cerrar sesión"><SidebarIcon name="logout" /><span>Cerrar sesión</span></button>
  </aside>;
}
