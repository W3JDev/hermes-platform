"""add missing tenant columns (plan, settings) that the model expects

Revision ID: 0003_tenant_columns
Revises: 0002_enable_rls
Create Date: 2026-09-29 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = '0003_tenant_columns'
down_revision: Union[str, None] = '0002_enable_rls'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("plan", sa.String(50), nullable=True, server_default="enterprise"))
    op.add_column("tenants", sa.Column("settings", JSONB, nullable=True, server_default=sa.text("'{}'::jsonb")))


def downgrade() -> None:
    op.drop_column("tenants", "settings")
    op.drop_column("tenants", "plan")
