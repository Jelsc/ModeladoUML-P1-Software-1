from alembic import op

revision = "0015_endpoint_specs"
down_revision = "0014_chat_channels"
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent: a fresh DB already has these objects through 0001's create_all.
    op.execute("""
        CREATE TABLE IF NOT EXISTS endpoint_specs (
            id UUID PRIMARY KEY,
            diagram_id UUID NOT NULL REFERENCES diagrams(id) ON DELETE CASCADE,
            class_id UUID NOT NULL REFERENCES uml_classes(id) ON DELETE CASCADE,
            name VARCHAR(60) NOT NULL,
            kind VARCHAR(20) NOT NULL,
            http_method VARCHAR(6) NOT NULL,
            path VARCHAR(160) NOT NULL,
            field VARCHAR(120),
            value VARCHAR(120),
            description VARCHAR(200) NOT NULL DEFAULT '',
            params JSON NOT NULL DEFAULT '[]',
            return_type VARCHAR(12),
            java_body TEXT,
            status VARCHAR(10) NOT NULL DEFAULT 'proposed',
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_endpoint_class_name UNIQUE (class_id, name)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_endpoint_specs_diagram ON endpoint_specs (diagram_id)")
    op.execute("ALTER TABLE deployments ADD COLUMN IF NOT EXISTS warning_summary VARCHAR(1500)")


def downgrade():
    # Destructive: drops every AI endpoint spec and the deployment warning.
    op.execute("ALTER TABLE deployments DROP COLUMN IF EXISTS warning_summary")
    op.execute("DROP INDEX IF EXISTS ix_endpoint_specs_diagram")
    op.execute("DROP TABLE IF EXISTS endpoint_specs")
