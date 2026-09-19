import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import { InvitationModal, Login } from "./components/index.jsx";
import { BoardEditor, Dashboard, SqlWorkspace, UserManagementPage } from "./pages/index.jsx";
import {
  AUTH_EXPIRED_EVENT,
  DIAGRAMS_REFRESH_EVENT,
  notifyAuthExpired,
  request,
} from "./api.js";

function App() {
  const [logged, setLogged] = useState(!!localStorage.getItem("token"));
  const [currentUser, setCurrentUser] = useState(null);
  const [authError, setAuthError] = useState("");
  const [route, setRoute] = useState(location.hash);
  const [theme, setTheme] = useState(
    () =>
      localStorage.getItem("uml-theme") ||
      document.documentElement.dataset.theme ||
      "dark",
  );
  const [invitation, setInvitation] = useState(null);
  const seenInvitations = useRef(new Set());
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("uml-theme", theme);
  }, [theme]);
  useEffect(() => {
    const onHash = () => setRoute(location.hash);
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    const onAuthExpired = () => logout();
    addEventListener(AUTH_EXPIRED_EVENT, onAuthExpired);
    return () => removeEventListener(AUTH_EXPIRED_EVENT, onAuthExpired);
  }, []);
  useEffect(() => {
    if (!logged) {
      setCurrentUser(null);
      return;
    }
    setAuthError("");
    request("/auth/me")
      .then(setCurrentUser)
      .catch((error) => {
        if (!error.authExpired) setAuthError(error.message);
      });
  }, [logged]);
  useEffect(() => {
    if (!logged || !currentUser) return undefined;
    let stopped = false,
      socket = null,
      timer = null,
      retry = 0;
    const connect = () => {
      if (stopped) return;
      const token = localStorage.getItem("token");
      if (!token) return;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(
        `${proto}://${location.host}/api/notifications/ws?token=${encodeURIComponent(token)}`,
      );
      socket.onopen = () => {
        retry = 0;
      };
      socket.onmessage = (event) => {
        let message;
        try {
          message = JSON.parse(event.data);
        } catch {
          return;
        }
        if (message.event !== "board.invitation" || !message.diagram_id) return;
        window.dispatchEvent(new CustomEvent(DIAGRAMS_REFRESH_EVENT));
        const key = message.diagram_id;
        if (seenInvitations.current.has(key)) return;
        seenInvitations.current.add(key);
        setInvitation({
          diagramId: message.diagram_id,
          diagramTitle: message.diagram_title || "Nueva pizarra",
          inviterName: message.inviter_name || "Otro usuario",
          memberRole: message.member_role || "viewer",
        });
      };
      socket.onclose = (event) => {
        if (stopped) return;
        if (event.code === 1008) {
          notifyAuthExpired();
          return;
        }
        timer = setTimeout(connect, Math.min(1000 * 2 ** retry, 5000));
        retry += 1;
      };
      socket.onerror = () => {};
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(timer);
      socket?.close();
      socket = null;
    };
  }, [logged, currentUser]);
  const id = route.match(/^#\/board\/([^/]+)/)?.[1];
  const sqlId = route.match(/^#\/board\/([^/]+)\/sql$/)?.[1];
  const userRoute = route === "#/gestion-usuarios";
  useEffect(() => {
    if (currentUser && userRoute && currentUser.role !== "admin")
      location.hash = "#/dashboard";
  }, [currentUser, userRoute]);
  function logout() {
    if (!localStorage.getItem("token") && !logged) return;
    localStorage.removeItem("token");
    seenInvitations.current.clear();
    setInvitation(null);
    setLogged(false);
    setCurrentUser(null);
    setAuthError("");
    if (location.hash !== "#/login") location.hash = "#/login";
  }
  function toggleTheme() {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
  }
  if (!logged)
    return (
      <Login
        onLogin={() => {
          setLogged(true);
          location.hash = "#/dashboard";
        }}
      />
    );
  if (!currentUser)
    return <main className="loading">{authError || "Cargando sesión..."}</main>;
  const content =
    userRoute && currentUser.role === "admin" ? (
      <UserManagementPage
        currentUser={currentUser}
        onLogout={logout}
        theme={theme}
        onThemeToggle={toggleTheme}
      />
    ) : sqlId ? (
      <SqlWorkspace
        id={sqlId}
        onBack={() => { location.hash = `#/board/${sqlId}`; }}
        onLogout={logout}
        currentUser={currentUser}
        theme={theme}
        onThemeToggle={toggleTheme}
      />
    ) : id ? (
      <BoardEditor
        id={id}
        onBack={() => {
          location.hash = "#/dashboard";
        }}
        onLogout={logout}
        currentUser={currentUser}
        theme={theme}
        onThemeToggle={toggleTheme}
      />
    ) : (
      <Dashboard
        currentUser={currentUser}
        onOpen={(boardId) => {
          location.hash = `#/board/${boardId}`;
        }}
        onLogout={logout}
        theme={theme}
        onThemeToggle={toggleTheme}
      />
    );
  return (
    <>
      {content}
      {invitation && (
        <InvitationModal
          invitation={invitation}
          onClose={() => setInvitation(null)}
          onOpen={() => {
            setInvitation(null);
            location.hash = `#/board/${invitation.diagramId}`;
          }}
        />
      )}
    </>
  );
}

createRoot(document.getElementById("root")).render(<App />);
