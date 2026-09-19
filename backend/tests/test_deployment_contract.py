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
    assert "networks: [uml-generated]" in COMPOSE
    assert "deploy_gateway_config" in COMPOSE
    assert "DeploymentPanel" in FRONTEND
    assert "onDeploy={owner ? () => setDeploymentOpen(true) : null}" in PAGES
