# Deployment

The root Compose file supports two modes selected by `APP_ENV`.

Generated deployments persist a dataset generation in the PostgreSQL volume. A fresh generated database gets a new generation; the mobile client invalidates remote cache and cursor for that generation, while preserving unsynchronized local operations as explicit conflicts that require a rebase. Restoring the same volume keeps the generation stable across container restarts.

All services use `America/La_Paz` for local presentation and SQL sessions. Persisted instants are UTC where the application owns them; client displays use Bolivia time explicitly.

The root backend migration `0007_timezone_aware_timestamps` converts existing PostgreSQL timestamp columns assuming their old values were Bolivia wall time. SQLite development databases are left unchanged by that migration.

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
