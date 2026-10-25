---
paths:
  - "frontend/**"
---

# Frontend rules

- React + Vite with hash routing implemented by hand: `#/dashboard`, `#/board/<id>`, `#/board/<id>/sql`, `#/gestion-usuarios` (admin UI only; backend `/admin/users` is the authority). Do not add a router library.
- Layout: `src/pages/` (page containers, `board-canvas.jsx` is the editor), `src/features/<feature>/` (assistant, canvas, deployment, diagram/inspector, members, photo-import, relations, sql), `src/components/` (auth, layout, icons), `src/api.js` (REST client, base `/api`, token in `localStorage`), `src/lib/diagram-normalizers.js`.
- `pages/board-canvas.jsx` is a thin (~60 lines) composition of `BoardCanvas` from `features/canvas/*` (ClassCard, RelationLayer, CollaboratorCursor, ZoomControls, `useCanvasCollaboration`, `useCanvasGestures`) plus panels re-exported through `components/index.jsx`; it exports `BoardEditor` and `SqlWorkspace` (same canvas with `initialSqlOpen`). Put new behavior in the feature modules, not in this file.
- Production serving: `frontend/nginx.conf` proxies `/api/` to `backend:8000` with WebSocket upgrade headers, returns 404 for dotfiles, and falls back to `index.html`.
- Pure logic (`relation-geometry.js`, `canvas-geometry.js`, `relation-context.js`, `features/relations/multiplicity-direction.js`, `features/photo-import/vision.js`) is imported by the Node check scripts without a DOM. Keep it free of React/DOM imports.
- Checks: `npm run check:<name>` (relation-geometry, relation-context, relation-inspector, relation-multiplicity, zoom, canvas-interaction, assistant, sidebar, deployment, module-structure, photo-import). Many check scripts read source files as text, so renaming or moving a file or string can break them; run the related check after edits.
- Dev server is in Docker with polling and `hmr.clientPort: 8080`; `/api` proxies to `http://backend:8000` and strips the `/api` prefix. Source edits never need a rebuild. Changing `package.json`/lockfile requires recreating the `frontend_node_modules` volume (ask first).
- Canvas behavior (documented in README): wheel = zoom 25-200% persisted per board, right-drag = pan, left = select/drag, class positions persist only on pointer release, cursor/move events coalesced to 16 ms.
- Viewers may generate/validate SQL but not apply it.
