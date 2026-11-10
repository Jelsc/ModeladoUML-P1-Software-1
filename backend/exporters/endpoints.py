"""Endpoints designed by the team AI: validation and Spring code generation (pure, DB-free).

A spec is either structured (`kind` from a small catalog, so the generated Java is predictable) or `custom`
(a Java method body written by the AI). Custom bodies are the only part that can fail to compile: the deployment
then falls back to plain CRUD and reports the compiler error (see app/deployment.py)."""

import re

from .validator import JAVA_KEYWORDS

HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
KINDS = ("find_by_field", "count", "sum_field", "set_field", "custom")
RETURNS = ("String", "Long", "Integer", "Boolean", "BigDecimal", "void", "entity", "list")
PARAM_TYPES = ("String", "Long", "Integer", "Boolean", "BigDecimal")
PARAM_SOURCES = ("path", "query")
SCALAR = {"string": "String", "integer": "Integer", "int": "Integer", "long": "Long", "decimal": "BigDecimal", "boolean": "Boolean"}
FIELD_TYPES = {"find_by_field": ("String", "Integer", "Long", "Boolean", "BigDecimal"), "sum_field": ("Integer", "Long", "BigDecimal"), "set_field": ("String", "Integer", "Long", "Boolean", "BigDecimal")}
RESERVED_NAMES = {"all", "byId", "create", "update", "delete", "findAll", "findById", "save", "repository", "service", "entity"}
MAX_BODY_CHARS, MAX_BODY_LINES, MAX_PARAMS, MAX_DESCRIPTION = 4000, 80, 4, 200
NAME = re.compile(r"^[a-z][A-Za-z0-9]{2,39}$")
PARAM_NAME = re.compile(r"^[a-z][A-Za-z0-9]{0,19}$")
SEGMENT = r"(?:[a-z][a-z0-9-]{0,29}|\{[a-z][A-Za-z0-9]{0,19}\})"
PATH = re.compile(rf"^/{SEGMENT}(?:/{SEGMENT}){{0,3}}$")
PATH_VARIABLE = re.compile(r"\{([a-z][A-Za-z0-9]*)\}")
# Best-effort guard for a local development MVP: the AI body must stay plain business logic over `repository` and the entity.
FORBIDDEN_JAVA = re.compile(r"\b(Runtime|ProcessBuilder|System\s*\.\s*(exit|getenv|getProperty|setProperty)|Class\s*\.\s*forName|ClassLoader|Thread|ScriptEngine|Unsafe|MethodHandle)\b|\bjava\s*\.\s*(io|nio|net|lang\s*\.\s*reflect)\b|\bjavax?\.(script|naming)\b|\bimport\b|\bpackage\b|\.exec\s*\(|\.getClass\s*\(|\.wait\s*\(|\.notify(All)?\s*\(")


def java_type(attribute_type):
    return SCALAR.get(str(attribute_type or "").lower())


def _kebab(name):
    return re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name).lower()


def _slug(value):
    return re.sub(r"[^a-z0-9]+", "", str(value).lower()) or "campo"


def _path_variables(path):
    return PATH_VARIABLE.findall(path)


def _route_key(method, path):
    return method, PATH_VARIABLE.sub("{}", path)


def validate_java_body(body):
    """Reason the AI-written method body is not acceptable, or None."""
    if not isinstance(body, str) or not body.strip(): return "El endpoint personalizado necesita un cuerpo Java"
    if len(body) > MAX_BODY_CHARS or body.count("\n") + 1 > MAX_BODY_LINES: return f"El cuerpo Java es demasiado largo (máximo {MAX_BODY_CHARS} caracteres y {MAX_BODY_LINES} líneas)"
    if body.count("{") != body.count("}"): return "El cuerpo Java tiene llaves sin cerrar"
    found = FORBIDDEN_JAVA.search(body)
    if found: return f"El cuerpo Java usa algo no permitido ({found.group(0).strip()[:30]})"
    return None


def prepare_spec(raw, attributes, used_names=(), used_routes=()):
    """Validate a raw spec (from the AI) against the class attributes [(name, type)] and fill the defaults.
    Returns (spec, None) or (None, reason)."""
    if not isinstance(raw, dict): return None, "Endpoint inválido"
    name, kind = str(raw.get("name") or "").strip(), raw.get("kind")
    if not NAME.fullmatch(name) or name in JAVA_KEYWORDS or name in RESERVED_NAMES: return None, f"Nombre de método inválido: {name[:40]!r} (use camelCase, por ejemplo buscarPorEmail)"
    if name in used_names: return None, f"Ya existe un endpoint llamado {name}"
    if kind not in KINDS: return None, f"Tipo de endpoint no soportado: {str(kind)[:30]!r} (use {', '.join(KINDS)})"
    spec = {"name": name, "kind": kind, "field": None, "value": None, "params": [], "return_type": None, "java_body": None, "description": str(raw.get("description") or "").strip()[:MAX_DESCRIPTION]}
    if kind in FIELD_TYPES:
        wanted = str(raw.get("field") or "").strip().lower()
        attribute = next(((n, t) for n, t in attributes if n.lower() == wanted), None)
        if attribute is None: return None, f"La clase no tiene el atributo {str(raw.get('field'))[:40]!r}"
        if java_type(attribute[1]) not in FIELD_TYPES[kind]: return None, f"El atributo {attribute[0]} ({attribute[1]}) no sirve para {kind}"
        spec["field"] = attribute[0]
    if kind == "set_field":
        literal_error = _literal(java_type(next(t for n, t in attributes if n == spec["field"])), raw.get("value"))[1]
        if literal_error: return None, literal_error
        spec["value"] = str(raw.get("value")).strip()
    if kind == "custom":
        error = validate_java_body(raw.get("java_body"))
        if error: return None, error
        spec["java_body"] = raw["java_body"].strip("\n")
        spec["return_type"] = raw.get("return_type") or "void"
        if spec["return_type"] not in RETURNS: return None, f"Tipo de retorno no soportado: {str(spec['return_type'])[:30]!r}"
        params = raw.get("params") or []
        if not isinstance(params, list) or len(params) > MAX_PARAMS: return None, f"Máximo {MAX_PARAMS} parámetros"
        seen = set()
        for p in params:
            pn, pt, ps = (str(p.get("name") or "") if isinstance(p, dict) else ""), (p.get("type") if isinstance(p, dict) else None), (p.get("source") if isinstance(p, dict) else None)
            if not PARAM_NAME.fullmatch(pn) or pn in JAVA_KEYWORDS or pn in seen or pn in RESERVED_NAMES: return None, f"Parámetro inválido: {pn[:20]!r}"
            if pt not in PARAM_TYPES or ps not in PARAM_SOURCES: return None, f"Parámetro {pn}: tipo ({', '.join(PARAM_TYPES)}) u origen ({', '.join(PARAM_SOURCES)}) no soportado"
            seen.add(pn); spec["params"].append({"name": pn, "type": pt, "source": ps})
    method = {"find_by_field": "GET", "count": "GET", "sum_field": "GET", "set_field": "POST"}.get(kind) or str(raw.get("http_method") or "").upper()
    if method not in HTTP_METHODS: return None, f"Método HTTP no soportado: {str(raw.get('http_method'))[:10]!r}"
    path = str(raw.get("path") or "").strip() or {"find_by_field": f"/por-{_slug(spec['field'])}", "count": "/contar", "sum_field": f"/total-{_slug(spec['field'])}", "set_field": f"/{{id}}/{_kebab(name)}"}.get(kind, "")
    if not PATH.fullmatch(path) or ".." in path: return None, f"Ruta inválida: {path[:40]!r} (use segmentos en minúsculas como /por-email o /{{id}}/activar)"
    variables = _path_variables(path)
    if variables and kind in ("find_by_field", "count", "sum_field"):  # these take no path variables (find_by_field reads ?value=): use the default route instead of rejecting the AI's proposal
        path = {"find_by_field": f"/por-{_slug(spec['field'])}", "count": "/contar", "sum_field": f"/total-{_slug(spec['field'])}"}[kind]; variables = []
    if path.split("/")[1].startswith("{") and len(path.split("/")) == 2: return None, "La ruta no puede ser solo una variable (choca con el CRUD)"
    expected = ["id"] if kind == "set_field" else [p["name"] for p in spec["params"] if p["source"] == "path"] if kind == "custom" else []
    if sorted(variables) != sorted(expected): return None, f"Las variables de la ruta {variables} no coinciden con los parámetros {expected}"
    if _route_key(method, path) in set(used_routes): return None, f"Ya existe un endpoint {method} {path} en esta clase"
    spec["http_method"], spec["path"] = method, path
    return spec, None


def route_key(spec): return _route_key(spec["http_method"], spec["path"])


def _literal(java, value):
    """(java literal, None) or (None, reason) for set_field values."""
    text = str(value if value is not None else "").strip()
    if java == "String":
        if not text or len(text) > 100 or re.search(r"[\x00-\x1f]", text): return None, "El valor de texto debe tener entre 1 y 100 caracteres"
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"', None
    if java == "Boolean": return (text.lower(), None) if text.lower() in ("true", "false") else (None, "El valor debe ser true o false")
    if java in ("Integer", "Long"): return (text + ("L" if java == "Long" else ""), None) if re.fullmatch(r"-?\d{1,9}", text) else (None, "El valor debe ser un número entero")
    if java == "BigDecimal": return (f'new java.math.BigDecimal("{text}")', None) if re.fullmatch(r"-?\d{1,12}(\.\d{1,6})?", text) else (None, "El valor debe ser un número decimal")
    return None, "Tipo de atributo no soportado"


def _cap(field): return field[0].upper() + field[1:]


def render(class_name, specs, fields):
    """Java for the approved specs of one class. `fields` maps attribute name (lowercase) -> (java field, java type) as the entity declares it.
    Returns ({"repository", "service", "controller"} code, [problems]); a spec that cannot be rendered is skipped and reported."""
    repo, service, controller, problems = [], [], [], []
    used_names, used_routes = set(), set()
    for spec in specs:
        try:
            name, kind = spec["name"], spec["kind"]
            if name in used_names or route_key(spec) in used_routes: problems.append(f"{name}: duplicado"); continue
            mapping, rel, verb = {"GET": "GetMapping", "POST": "PostMapping", "PUT": "PutMapping", "PATCH": "PatchMapping", "DELETE": "DeleteMapping"}, spec["path"], None
            verb = mapping[spec["http_method"]]; mapped = f'    @{verb}("{rel}") '
            if kind in FIELD_TYPES:
                resolved = fields.get(str(spec["field"]).lower())
                if not resolved or resolved[1] not in FIELD_TYPES[kind]: problems.append(f"{name}: el atributo {spec['field']} no existe en la clase generada"); continue
                field, jtype = resolved; cap = _cap(field)
            if kind == "find_by_field":
                repo.append(f"    java.util.List<{class_name}> findBy{cap}({_q(jtype)} value);")
                service.append(f"    public java.util.List<{class_name}> {name}({_q(jtype)} value) {{ return repository.findBy{cap}(value); }}")
                controller.append(f'{mapped}public java.util.List<{class_name}> {name}(@RequestParam("value") {_q(jtype)} value) {{ return service.{name}(value); }}')
            elif kind == "count":
                service.append(f"    public long {name}() {{ return repository.count(); }}")
                controller.append(f"{mapped}public long {name}() {{ return service.{name}(); }}")
            elif kind == "sum_field":
                if jtype == "BigDecimal":
                    service.append(f"    public java.math.BigDecimal {name}() {{ return repository.findAll().stream().map({class_name}::get{cap}).filter(java.util.Objects::nonNull).reduce(java.math.BigDecimal.ZERO, java.math.BigDecimal::add); }}")
                    controller.append(f"{mapped}public java.math.BigDecimal {name}() {{ return service.{name}(); }}")
                else:
                    service.append(f"    public long {name}() {{ return repository.findAll().stream().map({class_name}::get{cap}).filter(java.util.Objects::nonNull).mapToLong(Number::longValue).sum(); }}")
                    controller.append(f"{mapped}public long {name}() {{ return service.{name}(); }}")
            elif kind == "set_field":
                literal, error = _literal(jtype, spec["value"])
                if error: problems.append(f"{name}: {error}"); continue
                service.append(f"    public {class_name} {name}(Long id) {{ {class_name} entity = repository.findById(id).orElseThrow(); entity.set{cap}({literal}); return repository.save(entity); }}")
                controller.append(f'{mapped}public {class_name} {name}(@PathVariable("id") Long id) {{ return service.{name}(id); }}')
            elif kind == "custom":
                error = validate_java_body(spec.get("java_body"))
                if error: problems.append(f"{name}: {error}"); continue
                ret = {"entity": class_name, "list": f"java.util.List<{class_name}>"}.get(spec["return_type"]) or _q(spec["return_type"])  # qualified: the controller does not import BigDecimal
                signature = ", ".join(f"{_q(p['type'])} {p['name']}" for p in spec["params"])
                annotated = ", ".join(f'@{"PathVariable" if p["source"] == "path" else "RequestParam"}("{p["name"]}") {_q(p["type"])} {p["name"]}' for p in spec["params"])
                body = "\n".join("        " + line if line.strip() else "" for line in spec["java_body"].splitlines())
                service.append(f"    public {ret} {name}({signature}) {{\n{body}\n    }}")
                call = f"service.{name}({', '.join(p['name'] for p in spec['params'])})"
                controller.append(f"{mapped}public {ret} {name}({annotated}) {{ {'' if ret == 'void' else 'return '}{call}; }}")
            else:
                problems.append(f"{name}: tipo desconocido"); continue
            used_names.add(name); used_routes.add(route_key(spec))
        except (KeyError, TypeError, ValueError) as exc:
            problems.append(f"{spec.get('name', '?') if isinstance(spec, dict) else '?'}: especificación inválida ({type(exc).__name__})")
    join = lambda lines: "".join(line + "\n" for line in lines)
    return {"repository": join(repo), "service": join(service), "controller": join(controller)}, problems


def _q(jtype): return "java.math.BigDecimal" if jtype == "BigDecimal" else jtype
