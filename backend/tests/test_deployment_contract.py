from pathlib import Path

ROOT = Path(__file__).parents[2]
MAIN = (ROOT / "backend/app/main.py").read_text()
WORKER = (ROOT / "backend/app/deployment.py").read_text()
CREDENTIALS = (ROOT / "backend/app/deployment_credentials.py").read_text()
COMPOSE = (ROOT / "docker-compose.yml").read_text()
FRONTEND = (ROOT / "frontend/src/features/deployment/DeploymentPanel.jsx").read_text(encoding="utf-8")
PAGES = (ROOT / "frontend/src/pages/board-canvas.jsx").read_text()


def test_deployment_is_owner_only_and_has_lifecycle_endpoints():
    assert 'app.post("/diagrams/{diagram_id}/deployment"' in MAIN
    assert 'app.get("/diagrams/{diagram_id}/deployment"' in MAIN
    assert 'app.delete("/diagrams/{diagram_id}/deployment"' in MAIN
    assert 'app.get("/diagrams/{diagram_id}/deployment/credentials"' in MAIN
    assert 'app.get("/diagrams/{diagram_id}/deployment/postman"' in MAIN
    assert "owned(db, user, diagram_id)" in MAIN
    assert 'deployment.status != "running"' in MAIN
    assert '"Cache-Control": "no-store"' in MAIN
    assert '"Pragma": "no-cache"' in MAIN
    assert "deployment.project_json" in MAIN
    assert "status IN ('queued','building','starting','running','failed','stopped')" in (ROOT / "backend/alembic/versions/0006_deployments.py").read_text()


def test_worker_has_fixed_docker_surface_and_safe_paths():
    assert 'args[0] != "docker"' in WORKER
    assert '"--network", settings.DEPLOY_NETWORK' in WORKER
    assert 'f"uml-generated-data-{slug}:/var/lib/postgresql/data"' in WORKER
    assert '"--publish", "127.0.0.1::5432"' in WORKER
    assert "database_identity(deployment)" in WORKER
    assert "settings.DEPLOY_CREDENTIAL_SECRET or settings.JWT_SECRET" in WORKER
    assert "hmac.new(secret.encode()" in CREDENTIALS
    assert "SAFE_SLUG" in WORKER and "build_root.parent" in WORKER
    assert "DockerCommandError" in WORKER
    assert 'stage="build.compiler"' in WORKER
    assert "cleanup.image" in WORKER and "cleanup.volume" in WORKER
    assert 'deployment.url = None' in WORKER
    assert "DIAGNOSTIC_LIMIT = 1200" in WORKER
    assert 'role="alert"' in FRONTEND and "Diagnóstico del fallo" in FRONTEND
    assert "credentials.password" in FRONTEND and "navigator.clipboard.writeText" in FRONTEND
    assert "URL.revokeObjectURL" in FRONTEND


def test_gateway_isolated_and_frontend_wiring_exists():
    assert "deploy-gateway:" in COMPOSE
    assert "networks: [default, uml-generated]" in COMPOSE
    assert "deploy_gateway_config" in COMPOSE
    assert "DeploymentPanel" in FRONTEND
    assert "onDeploy={owner ? () => setDeploymentOpen(true) : null}" in PAGES


def test_deployment_ingress_is_environment_configurable_and_databases_are_private():
    config = (ROOT / "backend/app/config.py").read_text()
    worker = (ROOT / "backend/app/deployment.py").read_text()
    env = (ROOT / ".env.example").read_text()
    nginx = (ROOT / "infra/nginx/templates/default.prod.conf.template").read_text()
    assert "DEPLOY_PUBLIC_SCHEME" in config and "DEPLOY_PUBLIC_DOMAIN" in config
    assert "/deployments/{slug}" in worker
    assert '"--publish", "127.0.0.1::5432"' in worker
    assert "include /etc/nginx/generated/*.conf;" in nginx
    assert "server_name ${API_DOMAIN};" in (ROOT / "infra/nginx/templates/default.local.conf.template").read_text()
    assert "DEPLOY_PUBLIC_DOMAIN" in env and "APP_ENV=local" in env


def test_production_bootstrap_and_certificate_names_are_safe_and_consistent():
    nginx = (ROOT / "infra/nginx/nginx.conf").read_text()
    bootstrap = (ROOT / "infra/nginx/templates/default.prod-bootstrap.conf.template").read_text()
    production = (ROOT / "infra/nginx/templates/default.prod.conf.template").read_text()
    compose = COMPOSE
    assert "include /etc/nginx/generated/*.conf;" in bootstrap
    assert "include /etc/nginx/generated/*.conf;" in production
    assert "envsubst '$$FRONTEND_DOMAIN $$API_DOMAIN'" in compose
    assert "envsubst '$$FRONTEND_DOMAIN $$API_DOMAIN $$CERTBOT_CERT_NAME'" in compose
    assert "DEPLOY_CERT_NAME" not in compose
    assert "DEPLOY_CERT_NAME" not in (ROOT / "backend/app/config.py").read_text()
    assert "CERTBOT_CERT_NAME" in production
    assert "server_name ${API_DOMAIN};" in production
    assert "proxy_pass http://backend:8000;" in production
    assert production.index("server_name ${API_DOMAIN};") < production.index("include /etc/nginx/generated/*.conf;")
    assert '"--publish", "127.0.0.1::5432"' in (ROOT / "backend/app/deployment.py").read_text()


def test_nginx_hash_capacity_and_sensitive_path_guards_are_contractual():
    nginx = (ROOT / "infra/nginx/nginx.conf").read_text()
    bootstrap = (ROOT / "infra/nginx/templates/default.prod-bootstrap.conf.template").read_text()
    production = (ROOT / "infra/nginx/templates/default.prod.conf.template").read_text()
    assert "server_names_hash_bucket_size 128;" in nginx
    templates = [
        ROOT / "infra/nginx/templates/default.prod.conf.template",
        ROOT / "infra/nginx/templates/default.prod-bootstrap.conf.template",
        ROOT / "infra/nginx/templates/default.local.conf.template",
        ROOT / "frontend/nginx.conf",
    ]
    for template in templates:
        content = template.read_text()
        assert "location ~ (^|/)\\." in content
        assert "return 404;" in content
    assert "location ^~ /.well-known/acme-challenge/" in bootstrap
    assert "location ^~ /.well-known/acme-challenge/" in production
