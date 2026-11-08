from alembic import op

revision = "0014_chat_channels"
down_revision = "0013_diagram_visits"
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent: a fresh DB already has this column through 0001's create_all. Existing messages become the "diseno" chat.
    op.execute("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS channel VARCHAR(12) NOT NULL DEFAULT 'diseno'")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_messages_diagram_channel_created ON chat_messages (diagram_id, channel, created_at)")


def downgrade():
    # Destructive: drops the channel of every message (all chats merge back into one).
    op.execute("DROP INDEX IF EXISTS ix_chat_messages_diagram_channel_created")
    op.execute("ALTER TABLE chat_messages DROP COLUMN IF EXISTS channel")
