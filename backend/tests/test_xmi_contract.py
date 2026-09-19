from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_xmi_api_contract_keeps_access_and_confirmation_boundaries():
    main = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    assert '@app.get("/diagrams/{diagram_id}/xmi")' in main
    assert '@app.post("/diagrams/{diagram_id}/xmi/validate")' in main
    assert '@app.post("/diagrams/{diagram_id}/xmi/import")' in main
    assert "member_access(db, user, diagram_id)" in main
    assert "diagram = editable(db, user, diagram_id)" in main
    assert 'confirm: bool = Form(False)' in main
    assert 'raise HTTPException(409, "Confirme explícitamente el reemplazo del diagrama.")' in main
    assert "db.rollback()" in main
    assert 'await publish(diagram.id, "diagram.xmi_imported"' in main


def test_xmi_frontend_contract_has_member_export_editor_import_and_confirmation():
    topbar = (ROOT / "frontend" / "src" / "components" / "layout" / "TopBar.jsx").read_text(encoding="utf-8")
    board = (ROOT / "frontend" / "src" / "pages" / "board-canvas.jsx").read_text(encoding="utf-8")
    api = (ROOT / "frontend" / "src" / "api.js").read_text(encoding="utf-8")
    assert 'aria-label="Abrir menú XMI"' in topbar
    assert "Exportar XMI" in topbar and "Importar XMI" in topbar
    assert 'accept=".xmi,.xml,application/xml,text/xml"' in board
    assert "/xmi/validate" in board and "/xmi/import" in board
    assert "Confirmar reemplazo" in board and "setSelectedClassId(null)" in board
    assert "contentType.includes('xml')" in api
