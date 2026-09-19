import { useRef } from "react";

export function TopBar({ title, onBack, onExport, onExportXmi, onImportXmi, onAddClass, onMembers, onSql, sqlOpen = false, theme, onThemeToggle, onDeploy }) {
  const nextTheme = theme === "dark" ? "claro" : "oscuro";
  const menuRef = useRef(null);
  const closeMenu = () => { if (menuRef.current) menuRef.current.open = false; };
  return <header>
    {onBack && <button className="ghost context-back" onClick={onBack}>← Volver</button>}
    <span className="topbar-title">{title || ""}</span>
    {onSql && <button className="ghost sql-button" onClick={onSql} aria-pressed={sqlOpen}>{sqlOpen ? "Ocultar SQL" : "SQL Editor"}</button>}
    {onMembers && <button className="ghost" onClick={onMembers}>Miembros</button>}
    {onAddClass && <button onClick={onAddClass}>＋ Clase</button>}
    {onExport && <button className="ghost" onClick={onExport}>Exportar ZIP</button>}
    {(onExportXmi || onImportXmi) && <details className="xmi-menu" ref={menuRef}><summary className="ghost" aria-label="Abrir menú XMI">XMI</summary><div className="xmi-menu-items" role="menu">
      {onExportXmi && <button className="ghost" role="menuitem" onClick={() => { closeMenu(); onExportXmi(); }}>Exportar XMI</button>}
      {onImportXmi && <button className="ghost" role="menuitem" onClick={() => { closeMenu(); onImportXmi(); }}>Importar XMI</button>}
    </div></details>}
    {onDeploy && <button onClick={onDeploy}>Desplegar</button>}
    <button className="ghost theme-toggle" onClick={onThemeToggle} title={`Activar modo ${nextTheme}`} aria-label={`Activar modo ${nextTheme}`}>{theme === "dark" ? "☼ Claro" : "☾ Oscuro"}</button>
  </header>;
}
