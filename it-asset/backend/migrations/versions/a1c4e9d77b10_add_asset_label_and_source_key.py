"""add asset label_no and source_key

Revision ID: a1c4e9d77b10
Revises: f2b7e45c9a01
Create Date: 2026-07-13

"""
from alembic import op
import sqlalchemy as sa


revision = "a1c4e9d77b10"
down_revision = "f2b7e45c9a01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("label_no", sa.String(50), nullable=True))
    op.add_column("assets", sa.Column("source_key", sa.String(64), nullable=True))
    # SQLite 는 UNIQUE 제약을 나중에 붙일 수 없어서 batch(테이블 재생성)로 처리한다.
    with op.batch_alter_table("assets") as batch:
        batch.create_unique_constraint("uq_assets_source_key", ["source_key"])


def downgrade() -> None:
    op.drop_constraint("uq_assets_source_key", "assets", type_="unique")
    op.drop_column("assets", "source_key")
    op.drop_column("assets", "label_no")
