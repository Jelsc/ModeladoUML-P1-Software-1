"""Life cycle of an endpoint (pure, DB-free): the sequence of calls from the HTTP request down to the database and back,
its branches, what it depends on, who depends on it, and one suggested test per branch.

Structured endpoints (find_by_field, count, sum_field, set_field) have an exact flow because their Java comes from templates.
For `custom` endpoints the flow is read from the Java body line by line (if / else / for / while / throw / return, repository calls,
calls to other endpoints of the same service): it is a faithful outline of the code, not a symbolic execution."""

import re

from .endpoints import java_type, relative_path
from .validator import entity_route_path, resource_name

PARTICIPANTS = [("client", "Cliente HTTP"), ("controller", "Controller"), ("service", "Service"), ("repository", "Repository"), ("db", "Base de datos")]
CRUD_METHODS = {"findAll", "findById", "save", "delete"}
MAX_STEPS = 40
COND_LEN = 56  # condition text shown on a branch
REPO_SQL = (
    (re.compile(r"^(findById|getById|getReferenceById|findOne)$"), "SELECT * FROM {t} WHERE id = ?", "lee"),
    (re.compile(r"^findAll$"), "SELECT * FROM {t}", "lee"),
    (re.compile(r"^findBy(\w+)$"), "SELECT * FROM {t} WHERE {0} = ?", "lee"),
    (re.compile(r"^(existsById|existsBy\w*|count)$"), "SELECT COUNT(*) FROM {t}", "lee"),
    (re.compile(r"^(save|saveAndFlush)$"), "INSERT o UPDATE en {t} (según tenga id)", "escribe"),
    (re.compile(r"^saveAll$"), "INSERT o UPDATE de varias filas en {t}", "escribe"),
    (re.compile(r"^(delete\w*)$"), "DELETE FROM {t} …", "escribe"),
)


def _msg(src, dst, label, dashed=False): return {"kind": "message", "from": src, "to": dst, "label": label, "dashed": dashed}
def _self(at, label): return {"kind": "self", "at": at, "label": label}
def _note(at, label): return {"kind": "note", "at": at, "label": label}
def _short(text, n=70): text = re.sub(r"\s+", " ", str(text)).strip(); return text if len(text) <= n else text[: n - 1] + "…"
def _cap(name): return name[0].upper() + name[1:]


def _sql(method, table):
    for pattern, template, access in REPO_SQL:
        found = pattern.match(method)
        if found: return template.format(*(g.lower() for g in found.groups() if g), t=table), access
    return f"consulta sobre {table}", "lee"


def _repo_call(method, args, table, accesses):
    """service → repository → db and back, for one repository call."""
    sql, access = _sql(method, table); accesses.add(access)
    return [_msg("service", "repository", f"{method}({_short(args, 30)})"), _msg("repository", "db", sql), _msg("db", "repository", "filas / resultado", True), _msg("repository", "service", "resultado", True)]


def _request_label(spec, route):
    query = [p["name"] for p in spec.get("params") or [] if p.get("source") == "query"]
    if spec["kind"] == "find_by_field": query = ["value"]
    return f"{spec['http_method']} {route}" + (("?" + "&".join(f"{q}=…" for q in query)) if query else "")


def _structured(spec, cls, route, table, types):
    kind, name, field = spec["kind"], spec["name"], spec.get("field")
    C, jtype, accesses, warnings = cls, types.get((field or "").lower()), set(), []
    tests = []
    steps = [_msg("client", "controller", _request_label(spec, route))]
    if kind == "find_by_field":
        steps += [_msg("controller", "service", f"{name}(value)"), _msg("service", "repository", f"findBy{_cap(field)}(value)"), _msg("repository", "db", f"SELECT * FROM {table} WHERE {field.lower()} = ?"),
                  _msg("db", "repository", "filas que coinciden", True), _msg("repository", "service", f"List<{C}>", True), _msg("service", "controller", f"List<{C}>", True), _msg("controller", "client", "200 OK · JSON [ … ]", True)]
        accesses.add("lee")
        tests = [{"title": "Camino feliz", "given": f"existe un {C} con {field} = X", "request": f"{spec['http_method']} {route}?value=X", "expect": f"200 y la lista con ese {C}"},
                 {"title": "Sin coincidencias", "given": f"ningún {C} tiene ese {field}", "request": f"{spec['http_method']} {route}?value=Z", "expect": "200 y lista vacía []"},
                 {"title": "Falta el parámetro", "given": "", "request": f"{spec['http_method']} {route}", "expect": "400 (falta el parámetro obligatorio value)"}]
        if jtype in ("Integer", "Long", "BigDecimal"): tests.append({"title": "Tipo inválido", "given": "", "request": f"{spec['http_method']} {route}?value=abc", "expect": f"400 ({field} es {jtype})"})
    elif kind == "count":
        steps += [_msg("controller", "service", f"{name}()"), _msg("service", "repository", "count()"), _msg("repository", "db", f"SELECT COUNT(*) FROM {table}"), _msg("db", "repository", "n", True), _msg("repository", "service", "long", True), _msg("service", "controller", "long", True), _msg("controller", "client", "200 OK · número", True)]
        accesses.add("lee")
        tests = [{"title": "Con datos", "given": f"hay N registros de {C}", "request": f"{spec['http_method']} {route}", "expect": "200 y N"}, {"title": "Tabla vacía", "given": f"no hay registros de {C}", "request": f"{spec['http_method']} {route}", "expect": "200 y 0"}]
    elif kind == "sum_field":
        steps += [_msg("controller", "service", f"{name}()"), _msg("service", "repository", "findAll()"), _msg("repository", "db", f"SELECT * FROM {table}"), _msg("db", "repository", "todas las filas", True), _msg("repository", "service", f"List<{C}>", True),
                  _self("service", f"suma {field} (ignora los nulos)"), _msg("service", "controller", "total", True), _msg("controller", "client", "200 OK · número", True)]
        accesses.add("lee"); warnings.append("Carga todas las filas en memoria para sumar (findAll): con muchas filas conviene una consulta SUM en SQL.")
        tests = [{"title": "Con valores", "given": f"varios {C} con {field}", "request": f"{spec['http_method']} {route}", "expect": "200 y la suma exacta"}, {"title": "Valores nulos", "given": f"algún {C} con {field} nulo", "request": f"{spec['http_method']} {route}", "expect": "200 y los nulos no suman"},
                 {"title": "Sin filas", "given": f"no hay {C}", "request": f"{spec['http_method']} {route}", "expect": "200 y 0"}]
    else:  # set_field
        value = spec.get("value")
        found = [_msg("db", "repository", "la fila", True), _msg("repository", "service", f"Optional<{C}>", True), _self("service", f"entity.set{_cap(field)}({value})"), _msg("service", "repository", "save(entity)"), _msg("repository", "db", f"UPDATE {table} SET {field.lower()} = {value} WHERE id = ?"),
                 _msg("db", "repository", "fila actualizada", True), _msg("repository", "service", C, True), _msg("service", "controller", C, True), _msg("controller", "client", "200 OK · JSON { … }", True)]
        missing = [_msg("db", "repository", "sin filas", True), _msg("repository", "service", "Optional.empty", True), _self("service", "orElseThrow() → NoSuchElementException"), _msg("controller", "client", "500 · error (sin manejador: no se traduce a 404)", True)]
        steps += [_msg("controller", "service", f"{name}(id)"), _msg("service", "repository", "findById(id)"), _msg("repository", "db", f"SELECT * FROM {table} WHERE id = ?"), {"kind": "alt", "branches": [{"label": "existe", "steps": found}, {"label": "no existe", "steps": missing}]}]
        accesses.update({"lee", "escribe"}); warnings.append("Si el id no existe se lanza NoSuchElementException y la API responde 500: el proyecto generado no tiene un manejador que la convierta en 404.")
        tests = [{"title": "Camino feliz", "given": f"existe un {C} con id 1", "request": f"{spec['http_method']} {route.replace('{id}', '1')}", "expect": f"200 y {field} = {value}"},
                 {"title": "Id inexistente", "given": f"no existe un {C} con id 999", "request": f"{spec['http_method']} {route.replace('{id}', '999')}", "expect": "hoy 500 (NoSuchElementException); idealmente 404"},
                 {"title": "Repetirlo", "given": f"el {C} ya tiene {field} = {value}", "request": f"{spec['http_method']} {route.replace('{id}', '1')}", "expect": "200 y sigue igual (idempotente)"}]
    return steps, tests, [], accesses, warnings


# ---- custom (Java body) ----
CALL = re.compile(r"(?<![\w.])(?:this\.|service\.)?([a-z]\w*)\s*\(")
REPO = re.compile(r"\brepository\s*\.\s*(\w+)\s*\(([^;]*)")
THROW = re.compile(r"\bthrow\s+new\s+(\w+)")
RETURN = re.compile(r"^return\b\s*(.*?);?$")


def _calls(text, ctx):
    """Steps for the repository calls and the calls to other methods of the service found in `text` (a statement or a loop/if header)."""
    steps = []
    for method, args in REPO.findall(text): steps += _repo_call(method, args.split(")")[0], ctx["table"], ctx["access"]); ctx["repo"].add(method)
    for name in CALL.findall(re.sub(r"\brepository\s*\.\s*\w+\s*\(", "(", text)):
        if name in ctx["siblings"] and name != ctx["name"]: steps.append(_self("service", f"llama a {name}()")); ctx["calls"].append({"name": name, "kind": "endpoint", "reason": "lo invoca el cuerpo del método"})
        elif name in CRUD_METHODS: steps.append(_self("service", f"llama a {name}() del CRUD")); ctx["calls"].append({"name": name, "kind": "crud", "reason": "método del CRUD generado"})
    return steps


def _statement(line, ctx):
    """Steps of one simple statement (no braces)."""
    text = line.strip().rstrip(";")
    if not text: return []
    throw, steps = THROW.search(text), _calls(text, ctx)
    if throw:
        ctx["throws"].append(throw.group(1)); steps += [_self("service", f"lanza {throw.group(1)}"), _msg("controller", "client", f"error · {throw.group(1)}", True)]
        return steps
    ret = RETURN.match(text)
    if ret: steps.append(_msg("service", "controller", f"return {_short(ret.group(1), 40)}" if ret.group(1) else "return", True)); return steps
    if not steps: steps.append(_self("service", _short(text)))
    elif re.search(r"\.set[A-Z]\w*\(", text): steps.insert(0, _self("service", _short(re.sub(r"^\w[\w<>,\s]*\s(\w+)\s*=\s*", r"\1 = ", text), 60)))
    return steps


def _head(line):
    """(keyword, condition, opens_block, rest of the line) for `if (...)`, `while (...)` and `for (...)`, matching nested parentheses."""
    start = re.match(r"^(if|while|for)\s*\(", line)
    if not start: return None
    depth, open_at = 0, start.end() - 1
    for k in range(open_at, len(line)):
        depth += (line[k] == "(") - (line[k] == ")")
        if depth == 0:
            rest = line[k + 1:].strip(); brace = rest.startswith("{")
            return start.group(1), line[open_at + 1:k], brace, rest[1:].strip() if brace else rest
    return None


def _block(lines, i, ctx, depth=0):
    """Parse until the closing brace of the current block. Returns (steps, index of the closing line)."""
    steps = []
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith(("//", "/*", "*")): i += 1; continue
        if line.startswith("}"): return steps, i
        head = _head(line)
        if head:
            word, cond, brace, rest = head
            steps += _calls(cond, ctx)  # `for (X x : repository.findAll())` queries before it loops
            if not brace or rest.endswith("}"):  # body on the same line: `if (x) return y;` or `if (x) { return y; }`
                inner = _statement(rest.rstrip("}").strip(), ctx) if rest.rstrip("}").strip() else []
                steps.append({"kind": "alt", "branches": [{"label": _short(cond, COND_LEN), "steps": inner}]} if word == "if" else {"kind": "loop", "label": _short(cond, COND_LEN), "steps": inner}); i += 1; continue
            inner, i = _block(lines, i + 1, ctx, depth + 1)
            if word != "if": steps.append({"kind": "loop", "label": _short(cond, COND_LEN), "steps": inner}); i += 1; continue
            branches = [{"label": _short(cond, COND_LEN), "steps": inner}]
            while i < len(lines) and re.match(r"^\}\s*else", lines[i].strip()):
                closing = lines[i].strip(); elif_ = re.match(r"^\}\s*else\s+if\s*\((.*)\)\s*\{?$", closing)
                inner, i = _block(lines, i + 1, ctx, depth + 1); branches.append({"label": _short(elif_.group(1), COND_LEN) if elif_ else "si no", "steps": inner})
            steps.append({"kind": "alt", "branches": branches}); i += 1; continue
        steps += _statement(line, ctx); i += 1
    return steps, i


def _custom(spec, cls, route, table, siblings):
    ctx = {"table": table, "access": set(), "repo": set(), "calls": [], "throws": [], "siblings": {s["name"] for s in siblings}, "name": spec["name"]}
    body, _ = _block(spec["java_body"].splitlines(), 0, ctx)
    args = ", ".join(p["name"] for p in spec.get("params") or [])
    steps = [_msg("client", "controller", _request_label(spec, route)), _msg("controller", "service", f"{spec['name']}({args})")] + body
    if not any(s.get("kind") == "message" and s["from"] == "service" and s["to"] == "controller" for s in steps[2:]) and spec.get("return_type") == "void": steps.append(_msg("service", "controller", "void", True))
    steps.append(_msg("controller", "client", "200 OK" + ("" if spec.get("return_type") in (None, "void") else " · JSON"), True))
    tests = [{"title": "Camino feliz", "given": "datos válidos", "request": f"{spec['http_method']} {route}", "expect": "200 y el resultado esperado"}]
    def collect(items):
        for it in items:
            if it["kind"] == "alt":
                for b in it["branches"]:
                    if len(tests) < 8: tests.append({"title": f"Cuando {b['label']}", "given": b["label"], "request": f"{spec['http_method']} {route}", "expect": "recorre esta rama; verifique el resultado"})
                    collect(b["steps"])
            elif it["kind"] == "loop": collect(it["steps"])
    collect(body)
    for t in dict.fromkeys(ctx["throws"]): tests.append({"title": f"Provoca {t}", "given": "los datos que activan el error", "request": f"{spec['http_method']} {route}", "expect": f"error ({t})"})
    if any(p["source"] == "path" for p in spec.get("params") or []): tests.append({"title": "Id inexistente", "given": "el id no existe", "request": f"{spec['http_method']} {route}", "expect": "verifique que no devuelva 500 sin explicación"})
    return steps, tests, ctx["calls"], ctx["access"], []


def _count(steps):
    return sum(1 + (_count(sum((b["steps"] for b in s.get("branches", [])), []) or s.get("steps", [])) if s["kind"] in ("alt", "loop") else 0) for s in steps)


def _trim(steps, budget):
    out = []
    for s in steps:
        if budget[0] <= 0: break
        budget[0] -= 1
        if s["kind"] == "alt": s = {**s, "branches": [{**b, "steps": _trim(b["steps"], budget)} for b in s["branches"]]}
        elif s["kind"] == "loop": s = {**s, "steps": _trim(s["steps"], budget)}
        out.append(s)
    return out


def build_flow(spec, class_name, attributes, siblings=(), relations=()):
    """Life cycle of `spec` (a stored endpoint spec dict). `attributes` = [(name, type)], `siblings` = the other specs of the same class,
    `relations` = [{"other", "type", "multiplicity"}] of the class."""
    route = f"{entity_route_path(class_name)}{relative_path(class_name, spec['path'])}"; table = resource_name(class_name)
    types = {n.lower(): java_type(t) for n, t in attributes}
    siblings = [s for s in siblings if s.get("name") != spec["name"]]
    if spec["kind"] == "custom": steps, tests, calls, accesses, warnings = _custom(spec, class_name, route, table, siblings)
    else: steps, tests, calls, accesses, warnings = _structured(spec, class_name, route, table, types)
    total = _count(steps); steps = _trim(steps, [MAX_STEPS])
    if total > MAX_STEPS: warnings.append(f"El flujo tiene {total} pasos; se muestran los primeros {MAX_STEPS}.")
    calls = [dict(t) for t in {tuple(sorted(c.items())) for c in calls}]
    used_by = [{"name": s["name"], "reason": "su cuerpo llama a este método"} for s in siblings if s.get("java_body") and re.search(rf"(?<![\w.])(?:this\.|service\.)?{re.escape(spec['name'])}\s*\(", s["java_body"])]
    access = "lee y escribe" if {"lee", "escribe"} <= accesses else "escribe" if "escribe" in accesses else "lee"
    labels = {"client": "Cliente HTTP", "controller": f"{class_name}Controller", "service": f"{class_name}Service", "repository": f"{class_name}Repository", "db": f"BD · {table}"}
    flow = {"name": spec["name"], "title": f"{spec['http_method']} {route}", "class_name": class_name, "route": route, "http_method": spec["http_method"], "kind": spec["kind"], "status": spec.get("status", "proposed"),
            "description": spec.get("description") or "", "participants": [{"id": p, "label": labels[p]} for p, _ in PARTICIPANTS],
            "steps": steps, "calls": sorted(calls, key=lambda c: c["name"]), "used_by": used_by,
            "touches": [{"class": class_name, "access": access, "detail": f"tabla {table}"}], "related": [dict(r) for r in relations], "warnings": warnings, "tests": tests}
    flow["mermaid"] = to_mermaid(flow)
    return flow


def _label(text): return re.sub(r"\s+", " ", str(text).replace(";", ",").replace("#", "nº")).strip()


def to_mermaid(flow):
    """Mermaid `sequenceDiagram` text: paste it in a README, GitHub, Notion or mermaid.live to document the method."""
    lines = ["sequenceDiagram"] + [f"    participant {p['id']} as {_label(p['label'])}" for p in flow["participants"]]
    def emit(steps, indent):
        pad = "    " * indent
        for s in steps:
            if s["kind"] == "message": lines.append(f"{pad}{s['from']}{'-->>' if s.get('dashed') else '->>'}{s['to']}: {_label(s['label'])}")
            elif s["kind"] == "self": lines.append(f"{pad}{s['at']}->>{s['at']}: {_label(s['label'])}")
            elif s["kind"] == "note": lines.append(f"{pad}Note over {s['at']}: {_label(s['label'])}")
            elif s["kind"] == "loop": lines.append(f"{pad}loop {_label(s['label'])}"); emit(s["steps"], indent + 1); lines.append(f"{pad}end")
            elif s["kind"] == "alt":
                for index, b in enumerate(s["branches"]): lines.append(f"{pad}{'alt' if index == 0 else 'else'} {_label(b['label'])}"); emit(b["steps"], indent + 1)
                lines.append(f"{pad}end")
    emit(flow["steps"], 1)
    return "\n".join(lines)
