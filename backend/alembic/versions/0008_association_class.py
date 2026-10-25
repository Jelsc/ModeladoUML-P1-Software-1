from alembic import op

revision = "0008_association_class"
down_revision = "0007_timezone_aware_timestamps"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE uml_classes ADD COLUMN IF NOT EXISTS is_association BOOLEAN NOT NULL DEFAULT false")


def downgrade():
    op.execute("ALTER TABLE uml_classes DROP COLUMN IF EXISTS is_association")
