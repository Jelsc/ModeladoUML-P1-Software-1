from alembic import op

revision = "0010_chat_messages"
down_revision = "0009_relation_association_class"
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent: 0001 runs create_all with the current models, so a fresh DB already has this table.
    op.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id UUID PRIMARY KEY,
            diagram_id UUID NOT NULL REFERENCES diagrams(id) ON DELETE CASCADE,
            author_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            author_kind VARCHAR(10) NOT NULL DEFAULT 'user',
            content TEXT NOT NULL,
            reply_to_id UUID REFERENCES chat_messages(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_messages_diagram_created ON chat_messages (diagram_id, created_at)")


def downgrade():
    # Destructive: drops every stored chat message.
    op.execute("DROP INDEX IF EXISTS ix_chat_messages_diagram_created")
    op.execute("DROP TABLE IF EXISTS chat_messages")
