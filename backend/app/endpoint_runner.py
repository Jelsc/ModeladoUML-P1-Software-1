"""Runs the test cases of exporters/endpoint_tests.py against the deployed API (network injected, so it can be tested without one).

Safety: the base URL always comes from the deployment record (never from a request), cases that can change data run only when the team
confirmed it, and every call has a timeout plus a total time limit."""
import json
import time
import urllib.error
import urllib.request

REQUEST_TIMEOUT = 10
TOTAL_TIMEOUT = 60
MAX_BODY = 65536
NOT_FOUND_WARNING = "Responde 500 en vez de 404 cuando el registro no existe"


def http_call(method, url, timeout=REQUEST_TIMEOUT):
    """(status, body text, milliseconds). HTTP errors are answers, not exceptions; connection problems raise OSError."""
    request = urllib.request.Request(url, method=method, headers={"Accept": "application/json"})
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, body = response.status, response.read(MAX_BODY)
    except urllib.error.HTTPError as error:
        status, body = error.code, error.read(MAX_BODY)
    return status, body.decode(errors="replace"), int((time.monotonic() - started) * 1000)


def _body_ok(kind, text):
    try:
        if kind == "list": return isinstance(json.loads(text), list)
        if kind == "entity": data = json.loads(text); return isinstance(data, dict) and "id" in data
        if kind == "number": float(text.strip()); return True
        if kind == "boolean": return text.strip() in ("true", "false")
        if kind == "text": return len(text.strip()) > 0
    except (ValueError, TypeError):
        return False
    return True


def _check(case, status, text):
    """(passed, detail, warning) for one answer."""
    wanted, kind = case["expect"]["status"], case["expect"].get("body")
    if wanted == "2xx":
        if not 200 <= status < 300: return False, f"Respondió {status} y se esperaba 2xx", None
        if not _body_ok(kind, text): return False, f"Respondió {status} pero el cuerpo no es {({'list': 'una lista', 'entity': 'un registro', 'number': 'un número', 'boolean': 'true o false', 'text': 'texto'}).get(kind, kind)}", None
        return True, f"Respondió {status}", None
    if wanted == "400": return (status == 400, f"Respondió {status}" + ("" if status == 400 else " y se esperaba 400"), None)
    if status < 400: return False, f"Respondió {status} y se esperaba un error", None
    return True, f"Respondió {status}", NOT_FOUND_WARNING if status == 500 else None


def _url(base_url, case, record_id=None):
    path = case["path"].replace("{id}", str(record_id)) if record_id is not None else case["path"]
    query = "&".join(f"{key}={value}" for key, value in case.get("query", {}).items())
    return f"{base_url.rstrip('/')}{path}" + (f"?{query}" if query else "")


def _first_id(base_url, class_path, http):
    """Id of an existing record of the class (GET the list), or None when there are none."""
    try:
        status, text, _ = http("GET", f"{base_url.rstrip('/')}{class_path}")
        rows = json.loads(text) if 200 <= status < 300 else []
    except (OSError, ValueError):
        return None
    return next((row["id"] for row in rows if isinstance(row, dict) and "id" in row), None) if isinstance(rows, list) else None


def run_cases(cases, base_url, include_mutating=False, http=http_call, total_timeout=TOTAL_TIMEOUT, clock=time.monotonic):
    """One result per case: {case_id, endpoint, branch, title, method, path, status, ms, outcome: passed|failed|skipped, detail, warning}."""
    results, ids, started = [], {}, clock()
    for case in cases:
        result = {"case_id": case["id"], "endpoint": case["endpoint"], "branch": case["branch"], "title": case["title"], "method": case["method"], "path": case["path"],
                  "status": None, "ms": None, "outcome": "skipped", "detail": "", "warning": None}
        results.append(result)
        if clock() - started > total_timeout: result["detail"] = "Se alcanzó el tiempo máximo de la prueba"; continue
        if case["mutating"] and not include_mutating: result["detail"] = "Modifica datos: actívelo con «Incluir pruebas que modifican datos»"; continue
        record_id = None
        if case["needs_id"]:
            class_path = case["path"].split("/{id}")[0]
            if class_path not in ids: ids[class_path] = _first_id(base_url, class_path, http)
            record_id = ids[class_path]
            if record_id is None: result["detail"] = "No hay registros de esta clase: cree uno (Create) y vuelva a probar"; continue
        try:
            status, text, ms = http(case["method"], _url(base_url, case, record_id))
        except (OSError, TimeoutError) as error:
            result.update(outcome="failed", detail=f"No respondió ({type(error).__name__})"); continue
        passed, detail, warning = _check(case, status, text)
        result.update(status=status, ms=ms, outcome="passed" if passed else "failed", detail=detail, warning=warning)
    return results


def summarize(results):
    count = lambda outcome: sum(1 for item in results if item["outcome"] == outcome)
    return {"passed": count("passed"), "failed": count("failed"), "skipped": count("skipped"), "total": len(results)}
