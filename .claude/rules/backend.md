---
paths:
  - "backend/**"
---

# Backend rules

- Entry point: `backend/app/main.py` (`app = FastAPI`). Auth is JWT (`security.current_user`); WebSockets take the JWT as `?token=`. Routes: `/auth`, `/admin/users`, `/diagrams/...` (classes, relations, members, sql, xmi, export, deployment), `/classes`, `/details/{kind}`, `/relations`, `/assistant/{transcribe,parse,execute}`, `/vision/detect`, `/health`, WS `/diagrams/{id}/ws` and `/notifications/ws`.
- Roles: user role is `admin|editor|viewer`; per-diagram membership is `owner` / member `editor` / `viewer`. Use `permissions.owner/access/can_edit/member_access` in every route that touches a diagram. Do not hand-roll role checks.
- Deployment endpoints are owner-only.
- Realtime: mutate DB, commit, then `publish(diagram_id, event, payload)` (Redis channel `diagram:<id>`). A client must receive its own change once via the subscriber; do not echo directly.
- Config comes only from `app/config.py` (`Settings`, reads env/`.env`). Add new settings there with a safe default; also pass them in `docker-compose.yml` if the container needs them.
- Runtime is Python 3.12 (`python:3.12-slim`); `pytest` is not in `requirements.txt`.
- Schema changes: edit `models.py` AND add `alembic/versions/0008_*.py` (chain 0001 to 0007 is linear, verified via `down_revision`). Revision ids are the full filename stem. The container runs `alembic upgrade head && python -m app.seed` on start.
- How the existing chain works: `0001_initial` calls `Base.metadata.create_all` with the CURRENT models, so a fresh DB already has the final schema. 0002-0006 are idempotent raw SQL (`ADD COLUMN IF NOT EXISTS`, `CREATE TABLE IF NOT EXISTS`) so they are safe to replay on that DB; new revisions must be equally idempotent. 0004 promotes `demo@uml.local` to admin. 0005/0006 downgrades `drop_table`; 0001 downgrade `drop_all` (destructive). 0007 is PostgreSQL-only: converts 4 timestamp columns to `TIMESTAMPTZ` treating old values as `America/La_Paz` wall time; no-op on SQLite. DB session timezone is `America/La_Paz` (`app/db.py`).
- Seed (`app/seed.py`): only when `SEED_DEMO=true`; creates/keeps the demo admin user.
- Assistant (`app/assistant/`): `parser.parse` turns Spanish transcripts into an `AssistantCommand` (spaCy + regex; `DESTRUCTIVE` actions are rename/delete class, change/delete relation); `gemini.try_interpret` is an optional LLM interpreter that returns `None` without `GEMINI_API_KEY` or on any error (parser is the fallback); `executor.execute` applies a command to the DB via `can_edit` and publishes realtime events. It imports helpers lazily from `app.main` (`class_json`, `relation_json`, `touch_diagram`, `publish`, `relation_type`), so renaming those in `main.py` breaks it.
- Exporters (`backend/exporters/`) are pure and DB-free. Run `validator.normalize_diagram` before generating anything. `main.py` imports `export_zip` from `exporters.uml`, which re-exports `project_builder.export_zip`.
- `project_builder.build_project(diagram)` returns `{path: bytes}` for `generated-spring-backend/` (Spring Boot 3.2.4, Java 17, JPA + PostgreSQL, Dockerfile, compose, `schema.sql` from `sql_ddl`, UAP sources from `uap.py`, plus per-class model/repository/service/controller/dto); `export_zip` zips it. Everything is inline string templates (`_pom`, `_properties`, `_compose`, `_entity`, ...).
- Change those templates, then update the matching test (`test_exporter.py`, `test_uap_exporter.py`, `test_sql_ddl.py`, `test_xmi*.py`, `test_cardinality_generation.py`).
- Tests import via `sys.path.insert(0, backend/)`; run pytest from `backend/`. Tests named `*_contract.py` assert exact source text of `main.py` and of frontend files, so renaming or rewording code can break them.
- Known-stale contract tests (static analysis, Oct 2026; not re-run on Python 3.12): 18 tests in `test_frontend_contract.py`, `test_class_name_editing.py::test_detail_editor_*` and `test_collaboration_contract.py::test_read_edit_and_owner_*` fail because the asserted literals moved or were reworded, not because behavior is missing. The frontend contract tests only scan `*.jsx`, so logic that now lives in `.js` hooks/constants (`useCanvasCollaboration.js`, `useCanvasGestures.js`, `inspector.constants.js`, `relation-context.js`, `lib/diagram-normalizers.js`) is invisible to them. Updating them is a separate, explicit task: ask first; never edit tests just to pass.
- `test_class_name_editing.py::test_class_patch_contract_*` imports `app.main`, which needs the full `requirements.txt` (e.g. `passlib` via `security.py`); its failure in a minimal venv was an environment gap.
- Heavy optional deps (`faster-whisper`, `spacy`, `google-genai`) are in requirements; `GEMINI_API_KEY` is optional and must never be logged or committed.
