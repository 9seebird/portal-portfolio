"""add ip ranges and rental contracts

Revision ID: f2b7e45c9a01
Revises: 8c7c39ca6077
Create Date: 2026-06-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2b7e45c9a01"
down_revision: Union[str, Sequence[str], None] = "8c7c39ca6077"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ip_ranges",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("start_ip", sa.String(length=50), nullable=False),
        sa.Column("end_ip", sa.String(length=50), nullable=False),
        sa.Column("vlan", sa.String(length=50), nullable=True),
        sa.Column("gateway", sa.String(length=50), nullable=True),
        sa.Column("dns", sa.String(length=50), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "rental_contracts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("vendor", sa.String(length=100), nullable=False),
        sa.Column("contract_no", sa.String(length=100), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("monthly_fee", sa.Numeric(12, 2), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("ip_assignments", sa.Column("ip_range_id", sa.UUID(), nullable=True))
    # SQLite 는 FK 를 나중에 붙일 수 없어서 batch(테이블 재생성)로 처리한다.
    with op.batch_alter_table("ip_assignments") as batch:
        batch.create_foreign_key(
            "fk_ip_assignments_ip_range_id",
            "ip_ranges",
            ["ip_range_id"],
            ["id"],
        )


def downgrade() -> None:
    op.drop_constraint("fk_ip_assignments_ip_range_id", "ip_assignments", type_="foreignkey")
    op.drop_column("ip_assignments", "ip_range_id")
    op.drop_table("rental_contracts")
    op.drop_table("ip_ranges")
