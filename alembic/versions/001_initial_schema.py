"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id",                 sa.Integer(),     nullable=False),
        sa.Column("client_id",          sa.String(128),   nullable=False),
        sa.Column("company_name",       sa.String(256),   nullable=False),
        sa.Column("workspace_id",       sa.String(128),   nullable=False),
        sa.Column("model_id",           sa.String(128),   nullable=False),
        sa.Column("config_module_id",   sa.String(128),   nullable=False),
        sa.Column("target_module_id",   sa.String(128),   nullable=False),
        sa.Column("import_action_id",   sa.String(128),   nullable=False),
        sa.Column("commentary_file_id", sa.String(128),   nullable=False),
        sa.Column("credentials",        sa.Text(),        nullable=False),
        sa.Column("api_key_hash",       sa.String(64),    nullable=False),
        sa.Column("webhook_url",        sa.String(512),   nullable=True),
        sa.Column("created_at",         sa.DateTime(),    nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id"),
        sa.UniqueConstraint("api_key_hash"),
    )

    op.create_table(
        "usage_records",
        sa.Column("id",                    sa.Integer(),     nullable=False),
        sa.Column("client_id",             sa.String(128),   nullable=False),
        sa.Column("job_id",                sa.String(64),    nullable=False),
        sa.Column("source",                sa.String(32),    nullable=False),
        sa.Column("rows_generated",        sa.Integer(),     nullable=False),
        sa.Column("rows_skipped",          sa.Integer(),     nullable=False),
        sa.Column("input_tokens",          sa.Integer(),     nullable=False),
        sa.Column("output_tokens",         sa.Integer(),     nullable=False),
        sa.Column("cache_read_tokens",     sa.Integer(),     nullable=False),
        sa.Column("cache_creation_tokens", sa.Integer(),     nullable=False),
        sa.Column("created_at",            sa.DateTime(),    nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["tenants.client_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_client_id", "usage_records", ["client_id"])


def downgrade() -> None:
    op.drop_table("usage_records")
    op.drop_table("tenants")
