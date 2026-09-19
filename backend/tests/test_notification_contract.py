from pathlib import Path

ROOT = Path(__file__).parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
COLLABORATION = (ROOT / "app" / "collaboration.py").read_text(encoding="utf-8")


def test_invitation_uses_private_user_channel_and_safe_payload():
    assert 'await collaboration.publish_user(target.id' in MAIN
    assert '"event": "board.invitation"' in MAIN
    assert '"diagram_id": str(d.id)' in MAIN
    assert '"diagram_title": d.title' in MAIN
    assert '"inviter_name": user.name' in MAIN
    assert '"member_role": member.role' in MAIN
    assert '"password_hash"' not in MAIN
    assert 'f"user:{user_id}"' in COLLABORATION


def test_notification_websocket_authenticates_active_user_and_cleans_up():
    assert '@app.websocket("/notifications/ws")' in MAIN
    assert 'filter_by(id=user_id, active=True)' in MAIN
    assert 'await collaboration.join_user(key, websocket)' in MAIN
    assert 'await collaboration.leave_user(key, websocket)' in MAIN
    assert 'await websocket.close(code=1008)' in MAIN
