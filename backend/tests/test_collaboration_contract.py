from pathlib import Path

ROOT = Path(__file__).parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
MODELS = (ROOT / "app" / "models.py").read_text(encoding="utf-8")
PERMISSIONS = (ROOT / "app" / "permissions.py").read_text(encoding="utf-8")

def test_membership_model_is_unique_and_cascades():
    assert "__tablename__ = \"diagram_members\"" in MODELS
    assert "UniqueConstraint(\"diagram_id\", \"user_id\"" in MODELS
    assert 'ForeignKey("diagrams.id", ondelete="CASCADE")' in MODELS
    assert 'ForeignKey("users.id", ondelete="CASCADE")' in MODELS

def test_read_edit_and_owner_permissions_are_centralized():
    assert "def access(" in PERMISSIONS and "def can_edit(" in PERMISSIONS
    assert "return member_access(db, user, diagram_id)" in MAIN
    assert "d = editable(db, user, diagram_id)" in MAIN
    assert "d = owned(db, user, diagram_id); target" in MAIN
    assert 'd = owned(db, user, diagram_id); return StreamingResponse' in MAIN

def test_viewer_and_websocket_guards_and_public_member_payload():
    assert 'raise HTTPException(403, "Su acceso es de solo lectura")' in PERMISSIONS
    assert "access(db, ws_user, diagram_id)" in MAIN
    assert '"password_hash"' not in MAIN
    assert 'await publish(d.id, "member.added"' in MAIN

def test_ephemeral_events_validate_access_and_stay_out_of_persistence():
    assert 'class CursorMove(BaseModel)' in MAIN
    assert 'class ClassMove(BaseModel)' in MAIN
    assert 'event: Literal["cursor.move"]' in MAIN
    assert 'event: Literal["class.move"]' in MAIN
    assert 'can_edit(db, ws_user, diagram_id)' in MAIN
    assert 'source_connection_id' in MAIN
    assert 'presence.leave' in MAIN
    assert 'touch_diagram' not in MAIN.split('async def websocket(websocket', 1)[1].split('@app.websocket("/notifications/ws")', 1)[0]
