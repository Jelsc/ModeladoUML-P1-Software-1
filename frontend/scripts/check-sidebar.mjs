import { readFileSync } from "node:fs";

const components = readFileSync("src/components/index.jsx", "utf8");
const sidebar = readFileSync("src/components/layout/Sidebar.jsx", "utf8");
const topBar = readFileSync("src/components/layout/TopBar.jsx", "utf8");
const pages = readFileSync("src/pages/board-canvas.jsx", "utf8");

const checks = [
  [components.includes("./layout/Sidebar.jsx"), "Sidebar reutilizable"],
  [sidebar.includes('currentUser?.role === "admin"'), "enlace admin autorizado"],
  [pages.includes("<Sidebar currentUser={currentUser} onLogout={onLogout} />"), "Sidebar en páginas autenticadas"],
  [topBar.includes("onThemeToggle") && !topBar.includes("onLogout"), "sin cierre de sesión duplicado en TopBar"],
  [!topBar.includes('className="app-nav"') && !topBar.includes("Gestión de usuarios"), "sin navegación superior duplicada"],
];

const failures = checks.filter(([passed]) => !passed).map(([, label]) => label);
if (failures.length) {
  console.error(`Fallaron los checks del sidebar: ${failures.join(", ")}`);
  process.exit(1);
}
console.log(`Checks del sidebar OK (${checks.length})`);
