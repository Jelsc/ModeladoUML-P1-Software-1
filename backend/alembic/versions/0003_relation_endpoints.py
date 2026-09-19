from alembic import op

revision = "0003_relation_endpoints"
down_revision = "0002_relation_multiplicities"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TABLE relations ADD COLUMN IF NOT EXISTS source_endpoint UUID")
    op.execute("ALTER TABLE relations ADD COLUMN IF NOT EXISTS target_endpoint UUID")
    op.execute("ALTER TABLE relations ADD COLUMN IF NOT EXISTS source_endpoint_type VARCHAR(20) NOT NULL DEFAULT 'class'")
    op.execute("ALTER TABLE relations ADD COLUMN IF NOT EXISTS target_endpoint_type VARCHAR(20) NOT NULL DEFAULT 'class'")

def downgrade():
    op.execute("ALTER TABLE relations DROP COLUMN IF EXISTS target_endpoint_type")
    op.execute("ALTER TABLE relations DROP COLUMN IF EXISTS source_endpoint_type")
    op.execute("ALTER TABLE relations DROP COLUMN IF EXISTS target_endpoint")
    op.execute("ALTER TABLE relations DROP COLUMN IF EXISTS source_endpoint")
