import importlib.util, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from test_ai_brain import EDITOR, OWNER, class_names, env, reply  # noqa: F401  (shared fixture)


def post(env, user_id, text, channel=None, **extra):
    env.who["id"] = user_id; body = {"content": text, **extra}
    if channel: body["channel"] = channel
    return env.client.post(f"/diagrams/{env.diagram_id}/chat", json=body)


def chat(env, channel=None):
    env.who["id"] = OWNER
    return env.client.get(f"/diagrams/{env.diagram_id}/chat", params={"channel": channel} if channel else {}).json()


def test_default_channel_is_diseno_and_chats_are_separated(env):
    assert post(env, OWNER, "uno").json()["channel"] == "diseno"
    post(env, EDITOR, "dos", "desarrollo"); post(env, OWNER, "tres", "test")
    assert [m["content"] for m in chat(env)] == ["uno"]
    assert [m["content"] for m in chat(env, "diseno")] == ["uno"]
    assert [m["content"] for m in chat(env, "desarrollo")] == ["dos"]
    assert [m["content"] for m in chat(env, "test")] == ["tres"]


def test_unknown_channel_is_rejected(env):
    assert post(env, OWNER, "x", "otro").status_code == 422
    env.who["id"] = OWNER
    assert env.client.get(f"/diagrams/{env.diagram_id}/chat", params={"channel": "otro"}).status_code == 422


def test_ai_answers_in_the_same_channel_and_events_carry_it(env):
    env.llm.queue.append(reply("Ana, el flujo es POST y luego GET.", intent="explain"))
    q = post(env, OWNER, "@ia cómo va el flujo", "desarrollo").json()
    assert [m["author_kind"] for m in chat(env, "desarrollo")] == ["user", "ai"] and chat(env, "diseno") == []
    assert chat(env, "desarrollo")[-1]["reply_to_id"] == q["id"]
    by_event = {e: p for e, p in env.events}
    assert by_event["ai.thinking"]["channel"] == "desarrollo" and by_event["ai.done"]["channel"] == "desarrollo" and by_event["chat.message"]["message"]["channel"] == "desarrollo"


def test_only_diseno_can_edit_the_diagram(env):
    env.llm.queue.append(reply("ok", {"action": "create_class", "class_name": "Pedido"}))
    post(env, OWNER, "@ia creá la clase Pedido", "desarrollo")
    assert class_names(env) == [] and "chat es de consulta" in chat(env, "desarrollo")[-1]["content"]
    env.llm.queue.append(reply("ok", {"action": "create_class", "class_name": "Pedido"}))
    post(env, OWNER, "@ia creá la clase Pedido", "diseno")
    assert class_names(env) == ["Pedido"]
    env.llm.queue.append(reply("ok", {"action": "create_class", "class_name": "Otra"}))
    post(env, OWNER, "@ia creá la clase Otra", "test")
    assert class_names(env) == ["Pedido"]


def test_context_is_per_chat_and_dev_chat_sees_the_generated_backend(env):
    env.who["id"] = OWNER; env.client.post(f"/diagrams/{env.diagram_id}/classes", json={"name": "Cliente", "x": 0, "y": 0})
    post(env, EDITOR, "mensaje solo de diseño", "diseno")
    env.llm.queue.append(reply("listo", intent="explain"))
    post(env, OWNER, "@ia qué endpoints habrá", "desarrollo")
    prompt, system = env.llm.prompts[0], env.llm.systems[0]
    assert "mensaje solo de diseño" not in prompt and '"chat": "desarrollo"' in prompt
    assert "backend_generado" in prompt and "ClienteController" in prompt and "GET /" in prompt and "chat DESARROLLO" in system
    env.llm.queue.append(reply("listo", intent="explain"))
    post(env, OWNER, "@ia qué probamos", "test")
    assert "chat TEST" in env.llm.systems[1]
    env.llm.queue.append(reply("listo", intent="explain"))
    post(env, OWNER, "@ia hola", "diseno")
    assert "backend_generado" not in env.llm.prompts[2] and "chat DISEÑO" in env.llm.systems[2]


def test_reply_to_must_belong_to_the_same_channel(env):
    env.llm.queue.append(reply("hola", intent="chat"))
    q = post(env, OWNER, "@ia hola", "desarrollo").json(); ai = chat(env, "desarrollo")[-1]
    assert post(env, EDITOR, "sigamos", "test", reply_to_id=ai["id"]).status_code == 404
    assert q["channel"] == "desarrollo"


def test_migration_is_idempotent_and_chained():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0014_chat_channels.py"
    spec = importlib.util.spec_from_file_location("m0014", path); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    assert mod.revision == "0014_chat_channels" and mod.down_revision == "0013_diagram_visits"
    text = path.read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS channel" in text and "DEFAULT 'diseno'" in text and "CREATE INDEX IF NOT EXISTS" in text and "DROP COLUMN IF EXISTS channel" in text
