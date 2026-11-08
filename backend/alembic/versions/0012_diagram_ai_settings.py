from alembic import op

revision = "0012_diagram_ai_settings"
down_revision = "0011_activity_log"
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent: a fresh DB already has these columns through 0001's create_all.
    op.execute("ALTER TABLE diagrams ADD COLUMN IF NOT EXISTS ai_enabled BOOLEAN NOT NULL DEFAULT TRUE")
    op.execute("ALTER TABLE diagrams ADD COLUMN IF NOT EXISTS ai_can_edit BOOLEAN NOT NULL DEFAULT TRUE")


def downgrade():
    # Destructive: drops the per-diagram AI settings.
    op.execute("ALTER TABLE diagrams DROP COLUMN IF EXISTS ai_can_edit")
    op.execute("ALTER TABLE diagrams DROP COLUMN IF EXISTS ai_enabled")
