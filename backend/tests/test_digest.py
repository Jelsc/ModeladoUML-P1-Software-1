import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1]))

from test_ai_brain import EDITOR, OUTSIDER, OWNER, VIEWER, env, reply, say  # noqa: F401  (env is a shared fixture)


def digest(env, user_id):
    env.who["id"] = user_id
    return env.client.get(f"/diagrams/{env.diagram_id}/digest")


def seen(env, user_id):
    env.who["id"] = user_id
    return env.client.post(f"/diagrams/{env.diagram_id}/seen")


def new_class(env, user_id, name):
    env.who["id"] = user_id
    return env.client.post(f"/diagrams/{env.diagram_id}/classes", json={"name": name, "x": 0, "y": 0}).json()


def test_first_visit_has_nothing_to_catch_up_on_until_it_is_marked_as_seen(env):
    new_class(env, EDITOR, "Previa")
    first = digest(env, OWNER).json()
    assert first == {"since": None, "activity": [], "activity_total": 0, "chat_total": 0, "by_actor": {}}
    assert seen(env, OWNER).status_code == 200
    assert digest(env, OWNER).json()["since"] is not None and digest(env, OWNER).json()["activity_total"] == 0


def test_digest_lists_what_others_did_since_the_last_visit_and_never_my_own_actions(env):
    seen(env, OWNER)
    new_class(env, EDITOR, "Cliente"); new_class(env, OWNER, "Mia")
    say(env, EDITOR, "ya cree Cliente"); say(env, OWNER, "gracias")
    d = digest(env, OWNER).json()
    assert [a["summary"] for a in d["activity"]] == ["Beto creó la clase Cliente"]
    assert d["activity_total"] == 1 and d["chat_total"] == 1 and d["by_actor"] == {"Beto": 1}
    assert d["activity"][0]["actor_name"] == "Beto"


def test_reading_the_digest_does_not_move_the_cursor_but_marking_seen_does(env):
    seen(env, OWNER); new_class(env, EDITOR, "Cliente")
    assert digest(env, OWNER).json() == digest(env, OWNER).json() and digest(env, OWNER).json()["activity_total"] == 1
    seen(env, OWNER)
    assert digest(env, OWNER).json()["activity_total"] == 0 and digest(env, OWNER).json()["chat_total"] == 0


def test_each_member_has_an_independent_cursor(env):
    seen(env, OWNER); new_class(env, OWNER, "Mia")
    assert digest(env, EDITOR).json()["since"] is None
    seen(env, EDITOR); new_class(env, OWNER, "Otra")
    assert digest(env, EDITOR).json()["by_actor"] == {"Ana": 1}


def test_ai_work_is_reported_as_ia_and_its_replies_are_not_counted_as_chat(env):
    seen(env, OWNER)
    env.llm.queue.append(reply("Beto, listo.", {"action": "create_class", "class_name": "Pedido"}))
    say(env, EDITOR, "@ia creá Pedido")
    d = digest(env, OWNER).json()
    assert d["by_actor"] == {"IA": 1} and d["chat_total"] == 1 and d["activity"][0]["actor_kind"] == "ai"
    assert d["activity"][0]["summary"] == "IA (a pedido de Beto) creó la clase Pedido"


def test_digest_is_capped_to_the_latest_items_but_reports_the_real_total(env):
    seen(env, OWNER)
    for i in range(35): new_class(env, EDITOR, f"C{i}")
    d = digest(env, OWNER).json()
    assert d["activity_total"] == 35 and len(d["activity"]) == 30 and d["activity"][-1]["summary"].endswith("C34") and d["activity"][0]["summary"].endswith("C5")


def test_permissions_viewers_read_outsiders_do_not(env):
    assert digest(env, VIEWER).status_code == 200 and seen(env, VIEWER).status_code == 200
    assert digest(env, OUTSIDER).status_code == 403 and seen(env, OUTSIDER).status_code == 403


def test_the_ai_receives_what_the_requester_missed(env):
    seen(env, OWNER); new_class(env, EDITOR, "Zeta")
    env.llm.queue.append(reply("Ana, Beto creó Zeta.", intent="summary"))
    say(env, OWNER, "@ia qué pasó mientras no estaba")
    prompt = env.llm.prompts[0]
    assert '"desde_su_ultima_visita"' in prompt and "Beto creó la clase Zeta" in prompt
    assert "desde_su_ultima_visita" in env.llm.systems[0]


def test_ai_context_has_no_missed_items_on_a_first_visit(env):
    new_class(env, EDITOR, "Zeta")
    env.llm.queue.append(reply("ok", intent="chat")); say(env, OWNER, "@ia hola")
    assert '"desde_su_ultima_visita": {"fecha": null, "actividad": []}' in env.llm.prompts[0]


def test_migration_chain_is_linear_and_idempotent():
    text = (Path(__file__).parents[1] / "alembic/versions/0013_diagram_visits.py").read_text(encoding="utf-8")
    assert 'down_revision = "0012_diagram_ai_settings"' in text and "CREATE TABLE IF NOT EXISTS diagram_visits" in text
