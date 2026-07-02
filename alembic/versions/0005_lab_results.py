"""lab results

Sparse biomarker readings from blood panels. Keeps a parsed numeric value plus
the raw text (qualifiers like "<6", non-numeric like an APOE genotype) and the
lab's own optimal range, so out-of-range flagging needs no hardcoded intervals.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_lab_results"
down_revision: Union[str, None] = "0004_intake_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lab_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("marker", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=50)),
        sa.Column("value_num", sa.Numeric()),
        sa.Column("value_text", sa.String(length=100), nullable=False),
        sa.Column("qualifier", sa.String(length=4)),
        sa.Column("unit", sa.String(length=50)),
        sa.Column("optimal_low", sa.Numeric()),
        sa.Column("optimal_high", sa.Numeric()),
        sa.Column("optimal_text", sa.String(length=50)),
        sa.Column("source", sa.String(length=50), server_default="lab", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("date", "marker", "source", name="uq_lab_date_marker_source"),
    )
    op.create_index("ix_lab_results_date", "lab_results", ["date"])
    op.create_index("ix_lab_results_marker", "lab_results", ["marker"])


def downgrade() -> None:
    op.drop_index("ix_lab_results_marker", table_name="lab_results")
    op.drop_index("ix_lab_results_date", table_name="lab_results")
    op.drop_table("lab_results")
