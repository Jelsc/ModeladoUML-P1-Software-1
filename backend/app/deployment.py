import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .config import settings
from .db import SessionLocal
from .deployment_credentials import derive_database_identity, parse_database_runtime, redact_diagnostic
from .models import Deployment
from exporters.project_builder import build_project

SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,48}$")
SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,90}$")
DIAGNOSTIC_LIMIT = 1200
DATABASE_NAME = "uml_db"
DATABASE_PORT = "5432/tcp"


def diagnostic(stdout, stderr):
    value = stderr or stdout or "Sin salida diagnóstica"
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    value = str(value).strip()
    value = redact_diagnostic(value)
    return value[-DIAGNOSTIC_LIMIT:]


class DockerCommandError(RuntimeError):
    def __init__(self, stage, returncode, stdout="", stderr=""):
        self.stage = stage
        self.returncode = returncode
        super().__init__(f"stage={stage}; exit_code={returncode}; {diagnostic(stdout, stderr)}")


def slugify(title: str, diagram_id: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", title.lower().encode("ascii", "ignore").decode()).strip("-")
    value = (value[:36] or "diagram")
    slug = f"{value}-{str(diagram_id).replace('-', '')[:8]}"
    if not SAFE_SLUG.fullmatch(slug):
        raise ValueError("No se pudo generar un identificador seguro")
    return slug


def _run(args, timeout=120, stage=None):
    if not args or args[0] != "docker":
        raise ValueError("Comando Docker no permitido")
    command_stage = stage or (args[1] if len(args) > 1 else "docker")
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise DockerCommandError(command_stage, "timeout", getattr(exc, "stdout", ""), getattr(exc, "stderr", "")) from exc
    except OSError as exc:
        raise DockerCommandError(command_stage, "unavailable", "", str(exc)) from exc
    if result.returncode:
        raise DockerCommandError(command_stage, result.returncode, result.stdout, result.stderr)
    return result.stdout.strip()


def _safe_names(slug):
    names = (f"uml-generated-{slug}", f"uml-generated-db-{slug}", f"uml-generated-image-{slug}")
    if not all(SAFE_NAME.fullmatch(name) for name in names):
        raise ValueError("Identificador de despliegue inválido")
    return names


def database_identity(deployment: Deployment) -> tuple[str, str]:
    secret = settings.DEPLOY_CREDENTIAL_SECRET or settings.JWT_SECRET
    return derive_database_identity(secret, deployment.id, deployment.diagram_id, deployment.slug)


def inspected_database_port(container_name: str) -> int:
    if not container_name or not SAFE_NAME.fullmatch(container_name):
        raise RuntimeError("Contenedor de base de datos inválido")
    raw = _run(
        ["docker", "inspect", "--format", "{{json .}}", container_name],
        timeout=30,
        stage="database.runtime",
    )
    return parse_database_runtime(raw)


def database_credentials(deployment: Deployment) -> dict:
    username, password = database_identity(deployment)
    port = inspected_database_port(deployment.db_container_name)
    host = "127.0.0.1"
    return {
        "host": host,
        "port": port,
        "database": DATABASE_NAME,
        "username": username,
        "password": password,
        "jdbc_url": f"jdbc:postgresql://{host}:{port}/{DATABASE_NAME}",
        "postgresql_uri": f"postgresql://{username}:{password}@{host}:{port}/{DATABASE_NAME}",
    }


def _remove_container(name):
    _run(["docker", "rm", "-f", name], timeout=60) if _exists(name) else None


def _exists(name):
    return subprocess.run(["docker", "container", "inspect", name], capture_output=True, timeout=30).returncode == 0


def _exists_image(name):
    return subprocess.run(["docker", "image", "inspect", name], capture_output=True, timeout=30).returncode == 0


def _exists_volume(name):
    return subprocess.run(["docker", "volume", "inspect", name], capture_output=True, timeout=30).returncode == 0


def cleanup(deployment: Deployment):
    for name in (deployment.container_name, deployment.db_container_name):
        if name:
            try:
                _remove_container(name)
            except Exception:
                pass
    try:
        remove_route(deployment.slug)
    except Exception:
        pass
    if deployment.image_name and SAFE_NAME.fullmatch(deployment.image_name) and _exists_image(deployment.image_name):
        try:
            _run(["docker", "image", "rm", "-f", deployment.image_name], timeout=60, stage="cleanup.image")
        except Exception:
            pass
    volume = f"uml-generated-data-{deployment.slug}"
    if SAFE_NAME.fullmatch(volume) and _exists_volume(volume):
        try:
            _run(["docker", "volume", "rm", "-f", volume], timeout=60, stage="cleanup.volume")
        except Exception:
            pass


def _gateway_config(slug, container_name):
    if not SAFE_SLUG.fullmatch(slug) or not SAFE_NAME.fullmatch(container_name):
        raise ValueError("Ruta de gateway inválida")
    host = f"api-{slug}.{settings.DEPLOY_PUBLIC_DOMAIN}"
    proxy = f"server {{\n    listen 80;\n    server_name {host};\n    location / {{\n        proxy_pass http://{container_name}:8080;\n        proxy_http_version 1.1;\n        proxy_set_header Upgrade $http_upgrade;\n        proxy_set_header Connection $connection_upgrade;\n        proxy_set_header Host $host;\n        proxy_set_header X-Forwarded-Proto $scheme;\n        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n    }}\n}}\n"
    if settings.APP_ENV.lower() in {"prod", "production", "vm"}:
        proxy += f"server {{\n    listen 443 ssl;\n    server_name {host};\n    ssl_certificate /etc/letsencrypt/live/{settings.CERTBOT_CERT_NAME}/fullchain.pem;\n    ssl_certificate_key /etc/letsencrypt/live/{settings.CERTBOT_CERT_NAME}/privkey.pem;\n    location / {{\n        proxy_pass http://{container_name}:8080;\n        proxy_http_version 1.1;\n        proxy_set_header Upgrade $http_upgrade;\n        proxy_set_header Connection $connection_upgrade;\n        proxy_set_header Host $host;\n        proxy_set_header X-Forwarded-Proto $scheme;\n        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n    }}\n}}\n"
    return proxy


def write_route(slug, container_name):
    route_dir = Path(settings.DEPLOY_GATEWAY_CONFIG_DIR).resolve()
    route_dir.mkdir(parents=True, exist_ok=True)
    target = (route_dir / f"{slug}.conf").resolve()
    if target.parent != route_dir or not SAFE_SLUG.fullmatch(slug):
        raise ValueError("Ruta de gateway insegura")
    target.write_text(_gateway_config(slug, container_name), encoding="ascii")
    _reload_gateway()


def remove_route(slug):
    if not slug or not SAFE_SLUG.fullmatch(slug):
        return
    target = (Path(settings.DEPLOY_GATEWAY_CONFIG_DIR).resolve() / f"{slug}.conf").resolve()
    route_dir = Path(settings.DEPLOY_GATEWAY_CONFIG_DIR).resolve()
    if target.parent == route_dir:
        target.unlink(missing_ok=True)
    _reload_gateway()


def _reload_gateway():
    if _exists(settings.DEPLOY_GATEWAY_CONTAINER):
        _run(["docker", "exec", settings.DEPLOY_GATEWAY_CONTAINER, "nginx", "-s", "reload"], timeout=30)


def _wait_healthy(name, timeout=120):
    import time
    for _ in range(timeout // 5):
        raw = _run(["docker", "inspect", "--format", "{{if .State.Health}}{{.State.Health.Status}}{{else}}starting{{end}}", name], timeout=30)
        if raw == "healthy":
            return
        time.sleep(5)
    raise RuntimeError(f"stage=healthcheck; {name} no alcanzó estado saludable. Revisá el diagnóstico del contenedor generado.")


def _database_run_args(database, slug, username, password):
    return [
        "docker", "run", "--detach", "--name", database, "--network", settings.DEPLOY_NETWORK,
        "--network-alias", "db", "--memory", "256m", "--cpus", "0.5", "--pids-limit", "128",
        "--label", "uml.generated=true", "--label", f"uml.slug={slug}", "--publish", "127.0.0.1::5432",
        "--env", f"POSTGRES_DB={DATABASE_NAME}", "--env", f"POSTGRES_USER={username}",
        "--env", f"POSTGRES_PASSWORD={password}", "--env", "TZ=America/La_Paz", "--env", "PGTZ=America/La_Paz",
        "--health-cmd", f"pg_isready -U {username} -d {DATABASE_NAME}", "--health-interval", "5s",
        "--health-timeout", "3s", "--health-retries", "20", "--volume",
        f"uml-generated-data-{slug}:/var/lib/postgresql/data", "postgres:16-alpine",
    ]


def deploy(deployment_id):
    db = SessionLocal()
    deployment = db.get(Deployment, deployment_id)
    if not deployment:
        db.close()
        return
    try:
        deployment.status = "building"
        deployment.error_summary = None
        db.commit()
        slug = deployment.slug
        container, database, image = _safe_names(slug)
        deployment.container_name, deployment.db_container_name, deployment.image_name = container, database, image
        source = json.loads(deployment.project_json)
        files = build_project(source)
        digest = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
        build_root = Path(settings.DEPLOY_BUILD_DIR).resolve() / slug
        if build_root.parent != Path(settings.DEPLOY_BUILD_DIR).resolve():
            raise ValueError("Directorio de construcción inválido")
        shutil.rmtree(build_root, ignore_errors=True)
        for relative, content in files.items():
            target = (build_root / relative.removeprefix("generated-spring-backend/")).resolve()
            if build_root not in target.parents:
                raise ValueError("Archivo generado fuera del directorio controlado")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        deployment.project_hash = digest
        _remove_container(container)
        _remove_container(database)
        _run(["docker", "build", "--pull=false", "--tag", image, str(build_root)], timeout=settings.DEPLOY_BUILD_TIMEOUT, stage="build.compiler")
        _run(["docker", "volume", "create", f"uml-generated-data-{slug}"], timeout=30, stage="database.volume")
        database_username, database_password = database_identity(deployment)
        _run(_database_run_args(database, slug, database_username, database_password), timeout=60, stage="database.start")
        _wait_healthy(database)
        deployment.status = "starting"
        db.commit()
        _run(["docker", "run", "--detach", "--name", container, "--network", settings.DEPLOY_NETWORK,
              "--memory", "512m", "--cpus", "1", "--pids-limit", "256", "--restart", "on-failure:3",
               "--label", "uml.generated=true", "--label", f"uml.slug={slug}", "--env",
               f"SPRING_DATASOURCE_URL=jdbc:postgresql://db:5432/{DATABASE_NAME}", "--env", f"SPRING_DATASOURCE_USERNAME={database_username}",
                "--env", f"SPRING_DATASOURCE_PASSWORD={database_password}", image], timeout=60, stage="application.start")
        _wait_healthy(container, timeout=180)
        write_route(slug, container)
        deployment.status = "running"
        gateway_port = settings.DEPLOY_GATEWAY_HTTPS_PORT if settings.DEPLOY_PUBLIC_SCHEME == "https" else settings.DEPLOY_GATEWAY_PORT
        port = "" if gateway_port in (80, 443) else f":{gateway_port}"
        deployment.url = f"{settings.DEPLOY_PUBLIC_SCHEME}://api-{slug}.{settings.DEPLOY_PUBLIC_DOMAIN}{port}"
        deployment.updated_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        deployment.status = "failed"
        deployment.url = None
        deployment.error_summary = str(exc)[:500]
        try:
            cleanup(deployment)
        except Exception:
            pass
        deployment.updated_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()
