"""Replace dim_* columns with dimension_roles JSON

Revision ID: 002
Revises: 001
Create Date: 2026-05-18 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("form_configs", sa.Column("dimension_roles", JSONB, nullable=True, server_default="{}"))

    op.drop_column("form_configs", "dim_account")
    op.drop_column("form_configs", "dim_time")
    op.drop_column("form_configs", "dim_version")
    op.drop_column("form_configs", "dim_entity")
    op.drop_column("form_configs", "dim_commentary")


def downgrade() -> None:
    op.add_column("form_configs", sa.Column("dim_account",    sa.String(), nullable=True))
    op.add_column("form_configs", sa.Column("dim_time",       sa.String(), nullable=True))
    op.add_column("form_configs", sa.Column("dim_version",    sa.String(), nullable=True))
    op.add_column("form_configs", sa.Column("dim_entity",     sa.String(), nullable=True))
    op.add_column("form_configs", sa.Column("dim_commentary", sa.String(), nullable=True))

    op.drop_column("form_configs", "dimension_roles")
