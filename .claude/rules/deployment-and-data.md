---
paths:
  - "docker-compose.yml"
  - "infra/**"
  - "backend/app/deployment*.py"
  - "backend/alembic/**"
  - "frontend/nginx.conf"
  - "frontend/Dockerfile"
  - "backend/Dockerfile"
  - "docs/**"
---

# Deployment, data and secrets

## Compose services
`mongodb` (mongo:7, private port, healthchecked), `redis`, `backend` (MongoDB runtime; mounts `/var/run/docker.sock`, `deploy_build`, `deploy_gateway_config`, `whisper_models`), `frontend` (node:22 dev server, bind-mounts `./frontend`), `frontend-production` (profile `production`), `deploy-gateway` (nginx 1.27, picks a template from `infra/nginx/templates/` by `APP_ENV`), `certbot` (profile `production`). Network `uml-generated` joins the gateway and generated apps.

## Volumes (never delete without explicit user approval)
`mongodb_data` (platform MongoDB), `frontend_node_modules`, `deploy_build`, `deploy_gateway_config`, `whisper_models` (downloaded ASR models), `certbot_data` (TLS certificates), `certbot_www`. Names are prefixed by `COMPOSE_PROJECT_NAME` (default `primer-parcial-sw1`). The old `primer-parcial-sw1_postgres_data` test volume is orphaned and preserved; generated applications own separate per-deployment PostgreSQL volumes.

## Do not
- Run `docker compose down -v`, `docker volume rm/prune`, `docker system prune`, or delete/recreate `mongodb_data`, the orphaned `primer-parcial-sw1_postgres_data`, or `certbot_data`.
- Trigger deploy/rebuild/stop of generated deployments: rebuild and stop delete the generated PostgreSQL volume (ephemeral data, but still destructive).
- Widen the Docker-socket surface. `deployment.py` only runs a fixed, validated set of docker operations; names derive from a safe slug + UUID. Never accept commands, images, volumes or ports from the request.
- Commit or print `.env`, `JWT_SECRET`, `DEPLOY_CREDENTIAL_SECRET`, `GEMINI_API_KEY`, DB credentials, or certificates. `.env` is git-ignored and docker-ignored; keep it that way. Do not read `.env*`.
- Change `JWT_SECRET` or `DEPLOY_CREDENTIAL_SECRET` casually: it invalidates derived credentials and requires rebuilding existing deployments.
- Edit an applied Alembic revision. Add a new one; downgrade logic and data impact must be stated to the user first.

## Nginx (verified)
- `infra/nginx/nginx.conf`: main config of `deploy-gateway`; defines the WebSocket `$connection_upgrade` map and includes `conf.d/*.conf`.
- `infra/nginx/templates/`: `default.local.conf.template` (port 80, `API_DOMAIN`, includes generated per-deployment routes from `/etc/nginx/generated/*.conf`; everything else returns 404, so it never proxies the editor), `default.prod-bootstrap.conf.template` (HTTP only, ACME challenge, used until certificates exist), `default.prod.conf.template` (301 HTTP-to-HTTPS, TLS server blocks for the frontend domain [proxies `/api/` to backend and `/` to `frontend-production`] and the API domain [generated routes, then backend]). The compose `command` picks one with `envsubst` by `APP_ENV` and cert presence.
- `backend/app/deployment.py` writes/removes the per-deployment route files and reloads the gateway; do not hand-edit generated files in the `deploy_gateway_config` volume.
- `frontend/nginx.conf` is separate (prod frontend container).

## Python/tooling
Backend image is `python:3.12-slim` with `docker-cli`; Frontend dev/build is `node:22-alpine`; platform DB `mongo:7`; generated DBs remain `postgres:16-alpine`; Redis 7.

## Env variables (names only; template is `.env.example`)
- Required by compose: `JWT_SECRET`. Mongo connection/database values are `MONGODB_URL` and `MONGODB_DATABASE`; Compose supplies the internal service URL and a safe database default. `.env.example` ships placeholders only; real values go in the git-ignored `.env`.
- General: `COMPOSE_PROJECT_NAME` (prefixes containers, volumes, network; changing it orphans existing volumes), `CORS_ORIGINS`, `SEED_DEMO`, `GEMINI_API_KEY` (optional, empty by default), `DEPLOY_CREDENTIAL_SECRET` (optional, falls back to `JWT_SECRET`).
- Ports: `FRONTEND_PORT` (8080), `PRODUCTION_FRONTEND_PORT` (8081), `BACKEND_PORT` (8000), `DEPLOY_GATEWAY_PORT` (80), `DEPLOY_GATEWAY_HTTPS_PORT` (443).
- Mode/domains: `APP_ENV` (`local`; `prod|production|vm` switch the gateway to TLS templates), `FRONTEND_DOMAIN`, `API_DOMAIN`, `CERTBOT_CERT_NAME`, `DEPLOY_PUBLIC_SCHEME`, `DEPLOY_PUBLIC_DOMAIN`. `CERTBOT_EMAIL` is used only by the manual certbot command in `docs/deployment.md`, not by compose. The VM block in `.env.example` is commented out; enable it together with `APP_ENV=prod`. See `docs/deployment.md`.
- Keep real credentials and personal contact information out of `.env.example`; use placeholders only.

## Gotchas
- Backend code changes need `up --build backend`; frontend source edits do not need a rebuild in dev.
- Generated deployments are a local/dev MVP and unauthenticated; do not present them as production-ready.
- The gateway container name and `DEPLOY_NETWORK` are derived from `COMPOSE_PROJECT_NAME`; keep those consistent if you touch compose or `config.py`.
