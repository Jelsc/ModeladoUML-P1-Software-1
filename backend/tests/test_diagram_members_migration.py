from pathlib import Path


MIGRATION = (Path(__file__).parents[1] / "alembic/versions/0005_diagram_members.py").read_text()
DEPLOYMENTS = (Path(__file__).parents[1] / "alembic/versions/0006_deployments.py").read_text()


def test_diagram_members_migration_is_safe_to_resume_and_idempotent():
    assert 'down_revision = "0004_user_roles"' in MIGRATION
    assert 'CREATE TABLE IF NOT EXISTS diagram_members' in MIGRATION
    assert "ADD COLUMN IF NOT EXISTS" in MIGRATION
    assert "CREATE INDEX IF NOT EXISTS" in MIGRATION
    assert "DO $$" in MIGRATION
    assert "uq_diagram_member" in MIGRATION
    assert "ck_diagram_member_role" in MIGRATION
    assert "fk_diagram_members_diagram_id" in MIGRATION
    assert "fk_diagram_members_user_id" in MIGRATION
    assert "DROP TABLE" not in MIGRATION.split("def upgrade():", 1)[1].split("def downgrade():", 1)[0]


def test_following_revision_is_also_safe_after_a_partial_startup():
    assert 'down_revision = "0005_diagram_members"' in DEPLOYMENTS
    assert "CREATE TABLE IF NOT EXISTS deployments" in DEPLOYMENTS
    assert "ADD COLUMN IF NOT EXISTS" in DEPLOYMENTS
    assert "DROP TABLE" not in DEPLOYMENTS.split("def upgrade():", 1)[1].split("def downgrade():", 1)[0]
