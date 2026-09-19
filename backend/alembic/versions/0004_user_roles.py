from alembic import op

revision = "0004_user_roles"
down_revision = "0003_relation_endpoints"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'viewer'")
    op.execute("UPDATE users SET role = 'admin' WHERE lower(email) = 'demo@uml.local'")


def downgrade():
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS role")
