import base64
import hashlib
import hmac
import json
import re


CREDENTIAL_CONTEXT = b"uml-editor:deployment-database-credentials:v1\0"


def derive_database_identity(secret: str, deployment_id, diagram_id, slug: str) -> tuple[str, str]:
    context = CREDENTIAL_CONTEXT + f"deployment:{deployment_id}:{diagram_id}:{slug}".encode()
    digest = hmac.new(secret.encode(), context, hashlib.sha256).digest()
    username = f"uml_{hashlib.sha256(context).hexdigest()[:16]}"
    password = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return username, password


def parse_loopback_port(raw: str) -> int:
    try:
        bindings = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Docker devolvió un puerto de base de datos inválido") from exc
    if not isinstance(bindings, list) or len(bindings) != 1:
        raise RuntimeError("No se encontró un único puerto local para PostgreSQL")
    binding = bindings[0]
    if not isinstance(binding, dict):
        raise RuntimeError("Docker devolvió un enlace de puerto inválido")
    host_ip, host_port = binding.get("HostIp"), str(binding.get("HostPort", ""))
    if host_ip != "127.0.0.1" or not host_port.isdigit() or not 1 <= int(host_port) <= 65535:
        raise RuntimeError("El puerto de PostgreSQL no está publicado de forma segura")
    return int(host_port)


def parse_database_runtime(raw: str) -> int:
    try:
        inspection = json.loads(raw)
        state = inspection["State"]
        bindings = inspection["NetworkSettings"]["Ports"]["5432/tcp"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Docker devolvió un estado de PostgreSQL inválido") from exc
    if not isinstance(state, dict):
        raise RuntimeError("Docker devolvió un estado de PostgreSQL inválido")
    health = state.get("Health")
    if not state.get("Running") or state.get("Status") != "running":
        raise RuntimeError("El contenedor PostgreSQL no está en ejecución")
    if not isinstance(health, dict) or health.get("Status") != "healthy":
        raise RuntimeError("El contenedor PostgreSQL no está saludable")
    return parse_loopback_port(json.dumps(bindings))


def redact_diagnostic(value: str) -> str:
    return re.sub(
        r"(?i)(password|token|secret|authorization|docker_host)(\s*[:=]\s*)\S+",
        r"\1\2[redacted]",
        value,
    )
