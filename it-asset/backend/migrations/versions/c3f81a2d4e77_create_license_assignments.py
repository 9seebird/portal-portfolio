"""create license_assignments

직원에게 라이선스를 부여/회수한 기록을 담는다.
자산(asset_assignments)과 같은 구조로, 회수해도 행을 지우지 않고
released_at 을 채워 이력을 남긴다.

Revision ID: c3f81a2d4e77
Revises: a1c4e9d77b10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c3f81a2d4e77"
down_revision = "a1c4e9d77b10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "license_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "license_pool_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("license_pools.id"),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employees.id"),
            nullable=False,
        ),
        sa.Column("assigned_at", sa.Date(), nullable=True),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        sa.Column("release_reason", sa.String(length=20), nullable=True),
        sa.Column("note", sa.String(length=200), nullable=True),
    )

    # '지금 사용 중인 것'을 세는 조회가 가장 잦다.
    op.create_index(
        "ix_license_assignments_active",
        "license_assignments",
        ["license_pool_id", "released_at"],
    )
    op.create_index(
        "ix_license_assignments_employee",
        "license_assignments",
        ["employee_id", "released_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_license_assignments_employee", table_name="license_assignments")
    op.drop_index("ix_license_assignments_active", table_name="license_assignments")
    op.drop_table("license_assignments")
