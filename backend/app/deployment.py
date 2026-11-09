import hashlib
import json
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import settings
from .db import SessionLocal
from .deployment_credentials import derive_database_identity, parse_database_runtime, redact_diagnostic
from .models import ChatMessage, Deployment
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
        self.output = redact_diagnostic(f"{_text(stdout)}\n{_text(stderr)}")[-20000:]  # full (redacted) build log, used to extract compiler errors
        super().__init__(f"stage={stage}; exit_code={returncode}; {diagnostic(stdout, stderr)}")


def _text(value):
    return value.decode(errors="replace") if isinstance(value, bytes) else str(value or "")


COMPILE_ERROR = re.compile(r"\[ERROR\]\s+(\S+\.java):\[(\d+),\d+\][ \t]*([^\n]*)(?:\n[^\n]*?symbol:[ \t]*([^\n]*))?")


def compile_errors(output, limit=4):
    """Compiler messages (file, line, text and missing symbol) of a failed Maven build, so the team can see what the AI-written code got wrong.
    Maven prints each error twice (details, then summary): they are merged by file and line."""
    found = {}
    for match in COMPILE_ERROR.finditer(output or ""):
        key = (match.group(1).rsplit("/", 1)[-1], match.group(2))
        item = f"{key[0]} línea {key[1]}: {match.group(3).strip()[:160]}" + (f" ({match.group(4).strip()[:80]})" if match.group(4) else "")
        if key not in found or (match.group(4) and "(" not in found[key]):
            found[key] = item
    return list(found.values())[:limit]


def _write_project(build_root, files):
    shutil.rmtree(build_root, ignore_errors=True)
    for relative, content in files.items():
        target = (build_root / relative.removeprefix("generated-spring-backend/")).resolve()
        if build_root not in target.parents:
            raise ValueError("Archivo generado fuera del directorio controlado")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _announce(db, diagram_id, text):
    """Tell the team in the Desarrollo chat. Best effort: a notification problem must never fail the deployment."""
    try:
        from . import main
        message = ChatMessage(diagram_id=diagram_id, author_user_id=None, author_kind="ai", channel="desarrollo", content=text[:2000])
        db.add(message)
        db.commit()
        db.refresh(message)
        import redis
        redis.Redis.from_url(settings.REDIS_URL).publish(f"diagram:{diagram_id}", json.dumps({"event": "chat.message", "message": main.chat_json(message)}))
    except Exception:
        db.rollback()


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


def deployment_url(slug):
    if not SAFE_SLUG.fullmatch(slug):
        raise ValueError("URL de despliegue inválida")
    gateway_port = settings.DEPLOY_GATEWAY_HTTPS_PORT if settings.DEPLOY_PUBLIC_SCHEME == "https" else settings.DEPLOY_GATEWAY_PORT
    port = "" if gateway_port in (80, 443) else f":{gateway_port}"
    return f"{settings.DEPLOY_PUBLIC_SCHEME}://{settings.DEPLOY_PUBLIC_DOMAIN.rstrip('/')}{port}/deployments/{slug}"


def _gateway_config(slug, container_name):
    if not SAFE_SLUG.fullmatch(slug) or not SAFE_NAME.fullmatch(container_name):
        raise ValueError("Ruta de gateway inválida")
    prefix = f"/deployments/{slug}"
    return f"location = {prefix} {{\n    return 301 {prefix}/;\n}}\n\nlocation {prefix}/ {{\n    proxy_pass http://{container_name}:8080/;\n    proxy_http_version 1.1;\n    proxy_set_header Upgrade $http_upgrade;\n    proxy_set_header Connection $connection_upgrade;\n    proxy_set_header Host $host;\n    proxy_set_header X-Forwarded-Proto $scheme;\n    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n}}\n"


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
        deployment.warning_summary = None
        db.commit()
        slug = deployment.slug
        container, database, image = _safe_names(slug)
        deployment.container_name, deployment.db_container_name, deployment.image_name = container, database, image
        source = json.loads(deployment.project_json)
        endpoints = [spec for spec in source.get("endpoints") or [] if isinstance(spec, dict)]
        skipped = []
        files = build_project(source, report=skipped)
        digest = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
        build_root = Path(settings.DEPLOY_BUILD_DIR).resolve() / slug
        if build_root.parent != Path(settings.DEPLOY_BUILD_DIR).resolve():
            raise ValueError("Directorio de construcción inválido")
        _write_project(build_root, files)
        deployment.project_hash = digest
        _remove_container(container)
        _remove_container(database)
        build_command = ["docker", "build", "--pull=false", "--tag", image, str(build_root)]
        announcement = None
        if skipped:
            deployment.warning_summary = ("No se generaron estos endpoints: " + "; ".join(skipped))[:1500]
            announcement = f"⚠ Despliegue de {slug}: {deployment.warning_summary}"
        try:
            _run(build_command, timeout=settings.DEPLOY_BUILD_TIMEOUT, stage="build.compiler")
        except DockerCommandError as exc:
            if not endpoints:
                raise
            # Hybrid fallback: the AI endpoints did not compile, so deploy the plain CRUD and tell the team exactly why.
            errors = compile_errors(exc.output)
            names = ", ".join(f"{spec.get('class_name', '?')}.{spec.get('name', '?')}" for spec in endpoints)
            detail = "\n".join(f"• {item}" for item in errors) or f"• {diagnostic(exc.output, '')[-300:]}"
            _write_project(build_root, build_project(source, with_endpoints=False))
            _run(build_command, timeout=settings.DEPLOY_BUILD_TIMEOUT, stage="build.compiler")  # a second failure is not the AI endpoints' fault: it fails the deployment as usual
            deployment.warning_summary = (f"Los endpoints de la IA no compilaron; se desplegó solo el CRUD. Omitidos: {names}.\n{detail}")[:1500]
            announcement = f"⚠ El despliegue usó solo el CRUD porque los endpoints aprobados no compilaron.\nOmitidos: {names}.\nErrores del compilador:\n{detail}\nPídanme que los corrija en este chat y vuelvan a desplegar."
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
        deployment.url = deployment_url(slug)
        deployment.updated_at = datetime.now(timezone.utc)
        db.commit()
        if announcement:
            _announce(db, deployment.diagram_id, announcement)
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


def deploy_mongo(store, deployment_id):
    """Build the same generated Spring/PostgreSQL deployment from Mongo metadata."""
    deployment = store.deployments.find_one({"id": int(deployment_id)})
    if not deployment:
        return

    def update(**values):
        values["updated_at"] = datetime.now(timezone.utc)
        store.deployments.update_one({"id": int(deployment_id)}, {"$set": values})
        deployment.update(values)

    try:
        update(status="building", error_summary=None, warning_summary=None)
        slug = deployment["slug"]
        container, database, image = _safe_names(slug)
        update(container_name=container, db_container_name=database, image_name=image)
        source = json.loads(deployment["project_json"])
        endpoints = [spec for spec in source.get("endpoints") or [] if isinstance(spec, dict)]
        skipped = []
        files = build_project(source, report=skipped)
        digest = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
        build_root = Path(settings.DEPLOY_BUILD_DIR).resolve() / slug
        if build_root.parent != Path(settings.DEPLOY_BUILD_DIR).resolve():
            raise ValueError("Directorio de construcción inválido")
        _write_project(build_root, files)
        update(project_hash=digest)
        _remove_container(container)
        _remove_container(database)
        build_command = ["docker", "build", "--pull=false", "--tag", image, str(build_root)]
        announcement = None
        if skipped:
            warning = ("No se generaron estos endpoints: " + "; ".join(skipped))[:1500]
            update(warning_summary=warning)
            announcement = f"⚠ Despliegue de {slug}: {warning}"
        try:
            _run(build_command, timeout=settings.DEPLOY_BUILD_TIMEOUT, stage="build.compiler")
        except DockerCommandError as error:
            if not endpoints: raise
            errors = compile_errors(error.output)
            names = ", ".join(f"{item.get('class_name', '?')}.{item.get('name', '?')}" for item in endpoints)
            detail = "\n".join(f"• {item}" for item in errors) or f"• {diagnostic(error.output, '')[-300:]}"
            _write_project(build_root, build_project(source, with_endpoints=False))
            _run(build_command, timeout=settings.DEPLOY_BUILD_TIMEOUT, stage="build.compiler")
            warning = (f"Los endpoints de la IA no compilaron; se desplegó solo el CRUD. Omitidos: {names}.\n{detail}")[:1500]
            update(warning_summary=warning)
            announcement = f"⚠ El despliegue usó solo el CRUD porque los endpoints aprobados no compilaron.\nOmitidos: {names}.\nErrores del compilador:\n{detail}\nPídanme que los corrija en este chat y vuelvan a desplegar."
        _run(["docker", "volume", "create", f"uml-generated-data-{slug}"], timeout=30, stage="database.volume")
        deployment_record = type("DeploymentRecord", (), deployment)()
        database_username, database_password = database_identity(deployment_record)
        _run(_database_run_args(database, slug, database_username, database_password), timeout=60, stage="database.start")
        _wait_healthy(database)
        update(status="starting")
        _run(["docker", "run", "--detach", "--name", container, "--network", settings.DEPLOY_NETWORK,
              "--memory", "512m", "--cpus", "1", "--pids-limit", "256", "--restart", "on-failure:3",
              "--label", "uml.generated=true", "--label", f"uml.slug={slug}", "--env",
              f"SPRING_DATASOURCE_URL=jdbc:postgresql://db:5432/{DATABASE_NAME}", "--env", f"SPRING_DATASOURCE_USERNAME={database_username}",
              "--env", f"SPRING_DATASOURCE_PASSWORD={database_password}", image], timeout=60, stage="application.start")
        _wait_healthy(container, timeout=180)
        write_route(slug, container)
        update(status="running", url=deployment_url(slug), updated_at=datetime.now(timezone.utc))
        if announcement:
            _announce_mongo(store, deployment["diagram_id"], announcement)
    except Exception as exc:
        deployment.update(status="failed", url=None, error_summary=str(exc)[:500])
        try:
            cleanup(type("DeploymentRecord", (), deployment)())
        except Exception:
            pass
        update(status="failed", url=None, error_summary=str(exc)[:500])


def _announce_mongo(store, diagram_id, text):
    """Best-effort deployment notice with the same Desarrollo chat event contract."""
    try:
        message = {
            "id": str(uuid.uuid4()), "diagram_id": str(diagram_id), "author_user_id": None,
            "author_kind": "ai", "content": text[:2000], "reply_to_id": None,
            "channel": "desarrollo", "created_at": datetime.now(timezone.utc),
        }
        store.chat_messages.insert_one(message)
        payload = {**message, "author_name": None, "created_at": message["created_at"].isoformat()}
        from redis import Redis
        client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        client.publish(f"diagram:{diagram_id}", json.dumps({"event": "chat.message", "message": payload}))
        client.close()
    except Exception:
        pass
