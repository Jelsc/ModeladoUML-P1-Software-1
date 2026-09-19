from pathlib import Path


ROOT = Path(__file__).parents[2]
MAIN = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
SECURITY = (ROOT / "backend" / "app" / "security.py").read_text(encoding="utf-8")
PAGES = (ROOT / "frontend" / "src" / "pages" / "UserManagementPage.jsx").read_text(encoding="utf-8")
MAIN_JS = (ROOT / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")


def test_admin_routes_and_public_projection_exist():
    assert '@app.get("/auth/me")' in MAIN
    assert '@app.get("/admin/users")' in MAIN
    assert '@app.post("/admin/users", status_code=201)' in MAIN
    assert '@app.patch("/admin/users/{user_id}")' in MAIN
    assert '@app.delete("/admin/users/{user_id}")' in MAIN
    assert '"password_hash"' not in MAIN.split("def user_json", 1)[1].split("def admin_only", 1)[0]
    assert 'if user.role != "admin"' in MAIN


def test_security_uses_stable_user_id_and_invariants():
    assert '"sub": str(user_id)' in SECURITY
    assert 'filter_by(id=user_id, active=True)' in SECURITY
    assert "No puede dejar el sistema sin un administrador activo" in MAIN
    assert "No puede desactivarse ni quitarse el rol de administrador a sí mismo" in MAIN


def test_frontend_loads_me_and_wires_admin_crud():
    assert 'request("/auth/me")' in MAIN_JS
    assert 'currentUser.role === "admin"' in MAIN_JS
    for route in ("/admin/users", "item.id", "password", "Eliminar"):
        assert route in PAGES
