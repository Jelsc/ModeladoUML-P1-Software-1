"""Store application timestamps as instants while preserving Bolivia wall time."""

from alembic import op

revision = "0007_timezone_aware_timestamps"
down_revision = "0006_deployments"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column in (
        ("diagrams", "updated_at"),
        ("diagram_members", "created_at"),
        ("deployments", "created_at"),
        ("deployments", "updated_at"),
    ):
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE TIMESTAMPTZ "
            f"USING {column} AT TIME ZONE 'America/La_Paz'"
        )


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column in (
        ("diagrams", "updated_at"),
        ("diagram_members", "created_at"),
        ("deployments", "created_at"),
        ("deployments", "updated_at"),
    ):
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE TIMESTAMP "
            f"USING {column} AT TIME ZONE 'America/La_Paz'"
        )
