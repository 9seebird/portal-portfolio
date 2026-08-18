"""create seats

사무실 배치도. 엑셀 격자를 그대로 옮긴 좌표(row_idx/col_idx)와
병합 크기(row_span/col_span)를 가진다.

Revision ID: d5a2c81b3f40
Revises: c3f81a2d4e77
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d5a2c81b3f40"
down_revision = "c3f81a2d4e77"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seats",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("floor", sa.String(length=20), nullable=False),
        sa.Column("row_idx", sa.Integer(), nullable=False),
        sa.Column("col_idx", sa.Integer(), nullable=False),
        sa.Column("row_span", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("col_span", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("kind", sa.String(length=10), nullable=False, server_default="DESK"),
        sa.Column("label", sa.String(length=100), nullable=True),
        sa.Column("team", sa.String(length=50), nullable=True),
        sa.Column("marked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employees.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.UniqueConstraint("floor", "row_idx", "col_idx", name="uq_seats_floor_cell"),
        # 한 사람은 한 자리. NULL 은 중복 허용되므로 빈 자리는 제한 없다.
        sa.UniqueConstraint("employee_id", name="uq_seats_employee"),
    )

    # 배치도는 항상 "한 층 전체"를 한 번에 불러온다.
    op.create_index("ix_seats_floor", "seats", ["floor"])


def downgrade() -> None:
    op.drop_index("ix_seats_floor", table_name="seats")
    op.drop_table("seats")
