# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Collaborative UML class-diagram editor. It exports a diagram as a Spring Boot project, deploys that project locally with Docker, and a Flutter app talks to the deployed API through the UAP protocol. Docs are partly in Spanish (`README.md`, `MANUAL_USUARIO.md`, `docs/deployment.md`, `mobile/README.md`).

Detailed per-area rules load automatically from `.claude/rules/` when you touch matching paths: `backend.md`, `frontend.md`, `mobile.md`, `deployment-and-data.md`.

## Stack (verified in code)

- Backend: Python, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, Redis 7 (`backend/`).
- Frontend: React + Vite, plain JS/JSX, no router/test/lint libs (`frontend/`).
- Mobile: Flutter/Dart, llamadart (local GGUF LLM), sherpa_onnx (offline ASR), sqflite (`mobile/`).
- Infra: Docker Compose, Nginx (deploy gateway + prod frontend), certbot (prod profile).
- No XAMPP, MySQL or MariaDB anywhere in the repo. SQLite only appears as the `DB_URL` default in `backend/app/config.py`.

## Where things live

| Area | Location |
|---|---|
| REST + WebSocket API, all schemas | `backend/app/main.py` (single file, ~600 lines) |
| ORM models | `backend/app/models.py` |
| Migrations | `backend/alembic/versions/0001..0007` |
| Roles / access checks | `backend/app/permissions.py`, `security.py` |
| Realtime (Redis pub/sub) | `backend/app/collaboration.py` |
| Docker deployments | `backend/app/deployment.py`, `deployment_credentials.py` |
| AI assistant (Gemini) | `backend/app/assistant/` |
| Photo import | `backend/app/vision.py` (router `/vision`) |
| Code generation / export | `backend/exporters/` (`project_builder`, `sql_ddl`, `cardinality`, `uap`, `postman`, `xmi`, `uml`, `validator`) |
| Backend tests | `backend/tests/` |
| Frontend app | `frontend/src/` (`pages/`, `features/*`, `components/`, `api.js`) |
| Frontend checks | `frontend/scripts/check-*.mjs` |
| Nginx / TLS templates | `infra/nginx/`, `frontend/nginx.conf` |
| Flutter app | `mobile/lib/`, tests in `mobile/test/` |

## Commands

Docker is the supported way to run the system. A `.env` is required (`.env.example` is the template; `POSTGRES_DB/USER/PASSWORD` and `JWT_SECRET` are mandatory in compose).

```bash
docker compose --env-file .env up                               # dev: Vite HMR :8080, API :8000
docker compose --env-file .env up --build backend               # only after backend code/deps change
docker compose --env-file .env --profile production up --build  # prod bundle :8081 (+ certbot)
```

```bash
cd backend && pytest                                   # needs pytest + requirements; no DB/Docker needed
cd backend && pytest tests/test_sql_ddl.py::test_name  # one test
cd frontend && npm run check:<name>                    # one Node check; names are in package.json
cd mobile && flutter test [test/url_test.dart]         # also: flutter analyze, flutter pub get
```

Test caveats (details in `.claude/rules/backend.md` and `mobile.md`):
- Backend runs on Python 3.12 in Docker; `pytest` is not in any requirements file. Do not use the host's Python 3.14 (SQLAlchemy 2.0.36 fails to collect).
- Some `backend/tests/*_contract.py` tests are known-stale (they assert exact frontend source text). Do not edit tests or code to turn them green without asking.
- `flutter` commands may rewrite `mobile/analysis_options.yaml` and `mobile/pubspec.lock`; check `git status` afterwards.

No lint/typecheck exists for backend or frontend. Frontend build is `npm run build` (the prod Docker image runs it). `flutter build apk` needs `mobile/assets/models/assistant.gguf`, which is git-ignored and absent from a fresh checkout.

## Working rules

**Before any task**
1. Find the relevant files with Grep/Glob first; read only those, and only the needed line ranges. `main.py` is large, so grep for the route or schema name instead of reading it whole.
2. Never read or list: `node_modules/`, `dist/`, `__pycache__/`, `.pytest_cache/`, `package-lock.json`, `*.gguf`, `*.ort`, `*.eap`, `mobile/build/`, `mobile/.dart_tool/`, `backend/exporters/generated/`, `backend/exporters/json/`.
3. `.env.example` is readable (placeholders only); real `.env*` files are blocked and must never be read or edited. Variable names are already in `.claude/rules/deployment-and-data.md`, so read the template only for values. `.atl/` is Gentle AI tooling state, not project code: ignore it and do not commit its changes.
4. If code and README disagree, trust the code. Known stale spot: root README says Android `SpeechRecognizer`; the code uses sherpa_onnx (no `SpeechRecognizer` in `mobile/`).

**Scope and style**
- Do only what was asked. No drive-by refactors, renames, reformatting, dependency bumps, or new files unless required.
- Match the surrounding code. The backend is intentionally compact (multiple statements per line, short names); do not reformat existing lines you are not changing.
- Search for an existing helper before writing one (`exporters/validator.py`, `frontend/src/lib/`, `mobile/lib/core/`). Do not duplicate logic across `exporters/`, the frontend, and the backend.
- UI strings and API error messages in the app are Spanish. Code identifiers and comments are English unless the file already uses Spanish.
- Add or update a test with the change: backend in `backend/tests/`, frontend as a `check-*.mjs` (register it in `package.json`), mobile in `mobile/test/`.
- When adding or moving frontend modules, update `frontend/scripts/check-module-structure.mjs` (it asserts file existence).

**Safety (see `.claude/rules/deployment-and-data.md`)**
- Never run `docker compose down -v`, `docker volume rm/prune`, `docker system prune`, or delete/recreate the volumes named in compose without explicit approval.
- Never edit an existing Alembic revision. Add a new numbered one.
- Do not put secrets, tokens or real hostnames' credentials in code, docs or commits. `mobile/lib/config/api_config.dart` holds only public URLs.
- Do not start rebuilds, deployments or Docker-socket operations on your own initiative.
