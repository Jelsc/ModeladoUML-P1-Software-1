import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from exporters.endpoints import prepare_spec
from exporters.method_flow import MAX_STEPS, build_flow, to_mermaid

ATTRS = [("email", "string"), ("total", "decimal"), ("edad", "integer"), ("activo", "boolean")]


def spec(**raw):
    result, error = prepare_spec(raw, ATTRS); assert error is None, error
    return {**result, "status": "approved"}


def flow(s, siblings=(), relations=()): return build_flow(s, "Cliente", ATTRS, siblings, relations)


def labels(steps, kind="message"):
    out = []
    for s in steps:
        if s["kind"] == kind: out.append(s["label"])
        for b in s.get("branches", []): out += labels(b["steps"], kind)
        out += labels(s.get("steps", []), kind)
    return out


def everything(steps):
    out = []
    for s in steps:
        out.append(s)
        for b in s.get("branches", []): out += everything(b["steps"])
        out += everything(s.get("steps", []))
    return out


DISCOUNT = """Cliente c = repository.findById(id).orElseThrow();
if (porcentaje.compareTo(BigDecimal.ZERO) < 0) {
    throw new IllegalArgumentException("negativo");
} else if (porcentaje.compareTo(BigDecimal.ONE) > 0) {
    return c;
} else {
    BigDecimal base = c.getTotal() == null ? BigDecimal.ZERO : c.getTotal();
    c.setTotal(base.subtract(base.multiply(porcentaje)));
}
buscarPorEmail(c.getEmail());
for (Cliente otro : repository.findAll()) {
    otro.setActivo(true);
}
if (c.getTotal() == null) return null;
return repository.save(c);"""
CUSTOM = {"name": "aplicarDescuento", "kind": "custom", "http_method": "POST", "path": "/{id}/aplicar-descuento", "return_type": "entity",
          "params": [{"name": "id", "type": "Long", "source": "path"}, {"name": "porcentaje", "type": "BigDecimal", "source": "query"}], "java_body": DISCOUNT}


def test_find_by_field_flow_goes_from_http_to_the_table_and_back():
    f = flow(spec(name="buscarPorEmail", kind="find_by_field", field="email"))
    assert f["title"] == "GET /api/clientes/por-email" and [p["label"] for p in f["participants"]] == ["Cliente HTTP", "ClienteController", "ClienteService", "ClienteRepository", "BD · cliente"]
    sent = labels(f["steps"])
    assert sent[:5] == ["GET /api/clientes/por-email?value=…", "buscarPorEmail(value)", "findByEmail(value)", "SELECT * FROM cliente WHERE email = ?", "filas que coinciden"] and sent[-1] == "200 OK · JSON [ … ]"
    assert [t["title"] for t in f["tests"]] == ["Camino feliz", "Sin coincidencias", "Falta el parámetro"] and f["touches"] == [{"class": "Cliente", "access": "lee", "detail": "tabla cliente"}]
    assert "Tipo inválido" in [t["title"] for t in flow(spec(name="buscarPorEdad", kind="find_by_field", field="edad"))["tests"]], "numeric parameters add an invalid-type case"


def test_count_and_sum_flows():
    count = flow(spec(name="contarClientes", kind="count")); assert "SELECT COUNT(*) FROM cliente" in labels(count["steps"]) and count["warnings"] == []
    total = flow(spec(name="sumarTotales", kind="sum_field", field="total"))
    assert "findAll()" in labels(total["steps"]) and "suma total (ignora los nulos)" in labels(total["steps"], "self") and "memoria" in total["warnings"][0]


def test_set_field_flow_has_a_found_and_a_missing_branch_and_reports_the_500():
    f = flow(spec(name="activar", kind="set_field", field="activo", value="true"))
    alt = next(s for s in f["steps"] if s["kind"] == "alt")
    assert [b["label"] for b in alt["branches"]] == ["existe", "no existe"]
    assert "UPDATE cliente SET activo = true WHERE id = ?" in labels(alt["branches"][0]["steps"]) and "entity.setActivo(true)" in labels(alt["branches"][0]["steps"], "self")
    assert "NoSuchElementException" in f["warnings"][0] and f["touches"][0]["access"] == "lee y escribe" and f["title"] == "POST /api/clientes/{id}/activar"
    assert "Id inexistente" in [t["title"] for t in f["tests"]]


def test_custom_flow_follows_the_java_body():
    sibling = spec(name="buscarPorEmail", kind="find_by_field", field="email")
    f = flow({**spec(**CUSTOM)}, [sibling])
    steps = f["steps"]
    assert labels(steps)[:2] == ["POST /api/clientes/{id}/aplicar-descuento?porcentaje=…", "aplicarDescuento(id, porcentaje)"]
    assert "findById(id)" in labels(steps) and "SELECT * FROM cliente WHERE id = ?" in labels(steps) and "SELECT * FROM cliente" in labels(steps) and "INSERT o UPDATE en cliente (según tenga id)" in labels(steps)
    alt = next(s for s in steps if s["kind"] == "alt")
    assert [b["label"] for b in alt["branches"]] == ["porcentaje.compareTo(BigDecimal.ZERO) < 0", "porcentaje.compareTo(BigDecimal.ONE) > 0", "si no"]
    assert "lanza IllegalArgumentException" in labels(alt["branches"][0]["steps"], "self") and any(l.startswith("return c") for l in labels(alt["branches"][1]["steps"]))
    assert any(s["kind"] == "loop" and "otro : repository.findAll()" in s["label"] for s in steps), "a for loop is a loop block"
    assert "llama a buscarPorEmail()" in labels(steps, "self") and f["calls"] == [{"name": "buscarPorEmail", "kind": "endpoint", "reason": "lo invoca el cuerpo del método"}]
    assert f["touches"][0]["access"] == "lee y escribe" and labels(steps)[-1] == "200 OK · JSON"
    titles = [t["title"] for t in f["tests"]]
    assert "Camino feliz" in titles and "Provoca IllegalArgumentException" in titles and "Id inexistente" in titles and any(t.startswith("Cuando porcentaje.compareTo") for t in titles)


def test_who_depends_on_a_method_is_reported_from_the_other_side():
    custom = {**spec(**CUSTOM)}
    f = flow(spec(name="buscarPorEmail", kind="find_by_field", field="email"), [custom])
    assert f["used_by"] == [{"name": "aplicarDescuento", "reason": "su cuerpo llama a este método"}]
    assert flow(custom, [custom])["calls"] == [], "a method is not its own dependency"


def test_related_classes_and_crud_calls():
    body = {"name": "listar", "kind": "custom", "http_method": "GET", "path": "/listar", "return_type": "list", "params": [], "java_body": "List<Cliente> todos = findAll();\nreturn todos;"}
    f = flow(spec(**body), relations=[{"other": "Pedido", "type": "composition", "multiplicity": "1..*"}])
    assert f["calls"] == [{"name": "findAll", "kind": "crud", "reason": "método del CRUD generado"}] and f["related"] == [{"other": "Pedido", "type": "composition", "multiplicity": "1..*"}]


def test_long_bodies_are_trimmed_and_reported():
    body = {"name": "largo", "kind": "custom", "http_method": "GET", "path": "/largo", "return_type": "void", "params": [], "java_body": "\n".join(f"int v{i} = {i};" for i in range(70))}
    f = flow(spec(**body))
    assert len(everything(f["steps"])) == MAX_STEPS and "primeros 40" in f["warnings"][0]


def test_unusual_bodies_do_not_crash():
    for body in ("if (a) {\n  x();\n", "}\n}\nfoo();", "if (a(b(c))) { y(); } else { z(); }", "if ((a)\nreturn;", "// solo un comentario", "int a = 1; /* x */ return a;"):
        f = flow({**spec(**CUSTOM), "java_body": body})  # bypasses prepare_spec on purpose: the flow must survive whatever is stored
        assert f["steps"][0]["kind"] == "message" and f["mermaid"].startswith("sequenceDiagram")


def test_mermaid_text_is_valid_and_safe():
    f = flow(spec(**{**CUSTOM, "java_body": DISCOUNT.replace("negativo", "a;b#c")}))
    text = f["mermaid"]; lines = text.splitlines()
    assert lines[0] == "sequenceDiagram" and "    participant controller as ClienteController" in lines and "    client->>controller: POST /api/clientes/{id}/aplicar-descuento?porcentaje=…" in lines
    assert any(l.strip().startswith("alt ") for l in lines) and any(l.strip().startswith("else ") for l in lines) and any(l.strip().startswith("loop ") for l in lines)
    opened = sum(1 for l in lines if l.strip().split(" ")[0] in ("alt", "loop")); assert opened == sum(1 for l in lines if l.strip() == "end")
    assert all(";" not in l for l in lines[6:]) and to_mermaid(f) == text
    assert "-->>" in text and "->>" in text
