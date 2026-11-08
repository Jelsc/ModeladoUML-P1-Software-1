from alembic import op

revision = "0013_diagram_visits"
down_revision = "0012_diagram_ai_settings"
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent: 0001 runs create_all with the current models, so a fresh DB already has this table.
    op.execute("""
        CREATE TABLE IF NOT EXISTS diagram_visits (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            diagram_id UUID NOT NULL REFERENCES diagrams(id) ON DELETE CASCADE,
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, diagram_id)
        )
    """)


def downgrade():
    # Destructive: forgets when each member last saw each diagram.
    op.execute("DROP TABLE IF EXISTS diagram_visits")
