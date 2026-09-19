export function SidebarIcon({ name }) {
  const paths = {
    projects: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 9h18M8 4v5M16 4v5" /></>,
    users: <><circle cx="9" cy="8" r="3" /><path d="M3 20c.6-3 2.5-5 6-5s5.4 2 6 5M16 11a3 3 0 0 0 0-6M17 15c2.4.4 3.7 2 4 5" /></>,
    logout: <><path d="M10 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h5M14 16l4-4-4-4M18 12H8" /></>,
    menu: <><path d="M4 6h16M4 12h16M4 18h16" /></>,
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">{paths[name]}</svg>;
}
