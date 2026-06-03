"""oauth token store

Revision ID: 0002_oauth_tokens
Revises: 0001_initial
Create Date: 2026-06-03

Adds oauth_tokens so the Whoop consent flow can persist + refresh tokens in the
DB instead of requiring manual copy-paste into env vars.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_oauth_tokens"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oauth_tokens",
        sa.Column("provider", sa.String(length=50), primary_key=True),
        sa.Column("access_token", sa.Text()),
        sa.Column("refresh_token", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("oauth_tokens")
