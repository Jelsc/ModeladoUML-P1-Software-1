from alembic import op
revision = "0002_relation_multiplicities"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TABLE relations ADD COLUMN IF NOT EXISTS source_multiplicity VARCHAR(30)")
    op.execute("ALTER TABLE relations ADD COLUMN IF NOT EXISTS target_multiplicity VARCHAR(30)")

def downgrade():
    op.execute("ALTER TABLE relations DROP COLUMN IF EXISTS target_multiplicity")
    op.execute("ALTER TABLE relations DROP COLUMN IF EXISTS source_multiplicity")
