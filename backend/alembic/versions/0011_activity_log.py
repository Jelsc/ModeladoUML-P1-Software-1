from alembic import op

revision = "0011_activity_log"
down_revision = "0010_chat_messages"
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent: 0001 runs create_all with the current models, so a fresh DB already has this table.
    op.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id UUID PRIMARY KEY,
            diagram_id UUID NOT NULL REFERENCES diagrams(id) ON DELETE CASCADE,
            actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            actor_kind VARCHAR(10) NOT NULL DEFAULT 'user',
            action VARCHAR(40) NOT NULL,
            entity_type VARCHAR(20) NOT NULL,
            entity_id VARCHAR(36),
            summary VARCHAR(300) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_activity_log_diagram_created ON activity_log (diagram_id, created_at)")


def downgrade():
    # Destructive: drops the whole activity history.
    op.execute("DROP INDEX IF EXISTS ix_activity_log_diagram_created")
    op.execute("DROP TABLE IF EXISTS activity_log")
