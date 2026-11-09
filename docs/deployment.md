# Deployment

The root Compose file supports two modes selected by `APP_ENV`.

Generated deployments persist a dataset generation in the PostgreSQL volume. A fresh generated database gets a new generation; the mobile client invalidates remote cache and cursor for that generation, while preserving unsynchronized local operations as explicit conflicts that require a rebase. Restoring the same volume keeps the generation stable across container restarts.

All services use `America/La_Paz` for local presentation and SQL sessions. Persisted instants are UTC where the application owns them; client displays use Bolivia time explicitly.

The root backend migration `0007_timezone_aware_timestamps` converts existing PostgreSQL timestamp columns assuming their old values were Bolivia wall time. SQLite development databases are left unchanged by that migration.

## Fresh platform install

The platform now runs on MongoDB 7 by default. Compose starts an un-published MongoDB service, waits for its healthcheck, then starts the backend after MongoDB and Redis are healthy. The backend initializes Mongo indexes, seeds the optional demo administrator, and starts Uvicorn without running Alembic. PostgreSQL remains available only as an explicit historical/test mode.

1. Copy `.env.example` to `.env` and set a private `JWT_SECRET`.
2. Start the stack with `docker compose --env-file .env up -d --build --remove-orphans`.
3. Verify service health with `docker compose ps` and the backend health endpoint at `http://localhost:8000/health`.

Compose sets `PERSISTENCE_BACKEND=mongodb`, `MONGODB_URL=mongodb://mongodb:27017`, and `MONGODB_DATABASE` for the backend. The Mongo volume is named `${COMPOSE_PROJECT_NAME:-primer-parcial-sw1}_mongodb_data` and is created fresh. Existing platform PostgreSQL test data is not migrated: `--remove-orphans` removes the obsolete `db` container, while the previous `primer-parcial-sw1_postgres_data` volume remains untouched and orphaned. Do not remove it as part of this cutover.

The Mongo client is created during application startup, initializes indexes idempotently, and closes during shutdown. Set `PERSISTENCE_BACKEND=postgresql` only for historical SQL tests/development that also provide an appropriate `DB_URL`; in that mode the image retains the Alembic upgrade path.

## MongoDB platform document model

The Mongo-backed platform supports auth/admin, diagram and membership CRUD, classes/details/relations and settings, SQL/ZIP/XMI import/export, image review/apply, assistant parse/execute/chat turns, activity/digest/seen, deployment metadata/credentials/Postman, and the deployment background worker. AI turns stay queued per diagram, read/write the same Mongo identity and aggregate, and retain the existing realtime event shapes. It uses the aggregate document schema below, with chat, activity, visits, and deployment metadata in separate collections:

| Collection | Document identity and contents |
|---|---|
| `users` | Numeric public `id`, normalized unique `email`, name, password hash, role, active flag. Mongo `_id` is internal only. |
| `diagrams` | String UUID public `id`, numeric `owner_id`, title, UTC `updated_at`, AI settings; embedded `classes` (with `attributes` and `methods`), `relations`, and `members`. Settings are also grouped in a `settings` snapshot. |
| `counters` | Atomic numeric sequences for public user and member IDs. |
| `chat_messages`, `activity`, `visits`, `deployments` | Independently indexed records keyed to a diagram UUID; chat/activity authors keep numeric user references. |
| `admin_state` | One atomic active-admin ID registry; guarded removals cannot remove the final active administrator. |
| `device_tokens` | Unique FCM token, owning numeric user ID, platform, active flag, and creation/update timestamps. |

Unique/query indexes protect public user/email and diagram IDs, chat/activity pagination, visits, deployment-per-diagram metadata, and owner/member diagram listings. Image detection still depends on the configured external vision provider; provider configuration/availability errors retain their existing 503 response. Mongo seed/bootstrap provisions the demo administrator when `SEED_DEMO=true`.

## Firebase Cloud Messaging

The Android team observer receives generic push notifications for chat, UML, AI completion/proposal, and endpoint-approval activity. Presence and cursor updates are excluded. The payload contains only `diagram_id` and `event`; title/body are fixed generic text.

Keep the supplied Firebase files in the repository root: `firebase-adminsdk.json` (private server credential) and `google-services.json` (Android app configuration). Both are ignored by Git and Docker build context. Compose mounts the service account read-only at `/run/secrets/firebase-adminsdk.json` and configures `FIREBASE_CREDENTIALS_PATH`. If credentials are absent or invalid, the backend continues to start with push disabled; `/health` reports this as `push_available: false`. Never copy the service-account contents into configuration, logs, or source control.

The observer's Android module consumes its ignored `mobile-observer/android/app/google-services.json` copy through the Google Services Gradle plugin. That file must include an Android Firebase app registered as `com.primerparcial.mobile_observer`; a config for a different app ID does not build. Build it with `cd mobile-observer && flutter pub get && flutter build apk`. Users must grant notification permission; Android 13+ prompts at runtime. Login/session restore registers the current token, token refresh replaces it, and logout unregisters it. iOS intentionally remains unavailable until a separate `GoogleService-Info.plist` and APNs configuration are provided.

Verify by installing the observer on an Android device/emulator, signing in, granting permission, then generating diagram activity from another account and opening the notification. Backend unit tests validate sending behavior without real Firebase delivery. Hardware delivery is verified only when an actual configured device is available.

Deployment workers still build and run the same generated Spring Boot + PostgreSQL containers and preserve their named PostgreSQL volume behavior. Generated applications remain unchanged. The platform no longer depends on a Compose PostgreSQL service. PostgreSQL data is not copied or dual-written.

## Local

Keep the defaults in `.env.example` (or the equivalent values in `.env`):

```dotenv
APP_ENV=local
DEPLOY_PUBLIC_SCHEME=http
DEPLOY_PUBLIC_DOMAIN=localhost
```

The Vite frontend remains at `http://localhost:8080`. Generated APIs use `http://localhost/deployments/<slug>` through `deploy-gateway`. Generated databases are on the private Docker network and are only loopback-published for the existing credentials/debugging endpoint.

## VM

Set `APP_ENV=prod`, use the intended frontend and API domains, and set the generated deployment suffix to a DNS zone controlled by the VM:

```dotenv
APP_ENV=prod
FRONTEND_DOMAIN=app-primerpacialsw.duckdns.org
API_DOMAIN=api-primerpacialsw.duckdns.org
DEPLOY_PUBLIC_SCHEME=https
DEPLOY_PUBLIC_DOMAIN=api-primerpacialsw.duckdns.org
CERTBOT_CERT_NAME=app-primerpacialsw.duckdns.org
```

Only `deploy-gateway` owns public ports 80 and 443. It routes the frontend, API, WebSockets, and generated backends. The production frontend remains internal to the Compose network; its optional `8081` mapping is for local inspection only.

Start the production profile after DNS points the frontend and API records to the VM:

```text
docker compose --env-file .env --profile production up --build -d
```

The bootstrap Nginx configuration serves ACME webroot challenges over HTTP and deliberately does not include generated route files, because those files require the certificate. Request the certificate before enabling the certificate-backed configuration. Use the same `CERTBOT_CERT_NAME` for the Certbot certificate directory and generated Nginx routes:

```text
docker compose --env-file .env run --rm --entrypoint certbot certbot certonly --cert-name "$CERTBOT_CERT_NAME" --webroot -w /var/www/certbot -d "$FRONTEND_DOMAIN" -d "$API_DOMAIN" --email "$CERTBOT_EMAIL" --agree-tos --no-eff-email
docker compose --env-file .env --profile production restart deploy-gateway
```

Generated URLs are `https://api-primerpacialsw.duckdns.org/deployments/<slug>`. Only the fixed `app-primerpacialsw.duckdns.org` and `api-primerpacialsw.duckdns.org` DNS records are required; generated deployments are Nginx paths and do not need per-project or wildcard DNS records. Never expose generated services over plain HTTP in production.

Certbot renewal runs in the `certbot` service. After a successful renewal, reload or restart `deploy-gateway` so Nginx reads the renewed certificate.
