from alembic import op

revision = "0009_relation_association_class"
down_revision = "0008_association_class"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE relations ADD COLUMN IF NOT EXISTS association_class_id UUID REFERENCES uml_classes(id) ON DELETE SET NULL")


def downgrade():
    op.execute("ALTER TABLE relations DROP COLUMN IF EXISTS association_class_id")
