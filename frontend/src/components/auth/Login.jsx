import { useState } from "react";
import { json, request } from "../../api.js";

export function Login({ onLogin }) {
  const [email, setEmail] = useState("demo@uml.local"), [password, setPassword] = useState("demo123"), [error, setError] = useState("");
  return <main className="login"><section><p className="eyebrow">ESPACIO DE TRABAJO UML 2.5</p><h1>Modelar en equipo,<br /><i>entregar con claridad.</i></h1><p>Diagramas de clases colaborativos con proyectos persistentes y exportación.</p>
    <form onSubmit={async (e) => { e.preventDefault(); try { const x = await request("/auth/sign-in", json("POST", { email, password })); localStorage.setItem("token", x.access_token); onLogin(); } catch (x) { setError(x.message); } }}>
      <label>Correo electrónico<input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
      <label>Contraseña<input required type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
      {error && <small className="error">{error}</small>}<button>Ingresar al espacio de trabajo</button>
    </form><small>Demo: demo@uml.local / demo123</small></section></main>;
}
