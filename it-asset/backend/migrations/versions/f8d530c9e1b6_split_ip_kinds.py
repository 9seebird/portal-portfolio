"""IP 를 종류로 나눈다 — 네트워크(PC·서버) / 전화기.

전화기는 자산으로 등록하지 않으므로(대수가 많고 사양도 필요 없다) 내선번호를
전화기의 신원으로 삼는다. 그래서 ip_assignments 에 extension_id 를 두고,
asset_id 는 비어 있을 수 있게 푼다.

있던 IP 는 전부 자산에 붙어 있으므로 NETWORK 로 채워진다(server_default).

주의: SQLite 는 ALTER COLUMN 을 못 해서 batch_alter_table 로 표를 다시 만든다.
그래야 로컬(SQLite)과 서버(Postgres) 양쪽에서 같은 마이그레이션이 돈다.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f8d530c9e1b6"
down_revision = "e7c419b8d2a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ip_assignments") as batch:
        batch.add_column(
            sa.Column("kind", sa.String(length=20), nullable=False, server_default="NETWORK")
        )
        batch.add_column(
            sa.Column("extension_id", postgresql.UUID(as_uuid=True), nullable=True)
        )
        # 전화기 IP 는 자산이 없다
        batch.alter_column(
            "asset_id",
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=True,
        )
        batch.create_foreign_key(
            "fk_ip_assignments_extension_id",
            "extensions",
            ["extension_id"],
            ["id"],
            ondelete="SET NULL",
        )
        # 내선 하나에 전화기 IP 하나
        batch.create_unique_constraint("uq_ip_assignments_extension", ["extension_id"])

    with op.batch_alter_table("ip_ranges") as batch:
        batch.add_column(
            sa.Column("kind", sa.String(length=20), nullable=False, server_default="NETWORK")
        )


def downgrade() -> None:
    # 전화기 IP 는 자산이 없어서 asset_id 를 다시 NOT NULL 로 되돌릴 수 없다.
    # 되돌리기 전에 지운다 — 어차피 이 판 이전에는 있을 수 없던 자료다.
    op.execute("DELETE FROM ip_assignments WHERE kind = 'PHONE'")

    with op.batch_alter_table("ip_ranges") as batch:
        batch.drop_column("kind")

    with op.batch_alter_table("ip_assignments") as batch:
        batch.drop_constraint("uq_ip_assignments_extension", type_="unique")
        batch.drop_constraint("fk_ip_assignments_extension_id", type_="foreignkey")
        batch.alter_column(
            "asset_id",
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=False,
        )
        batch.drop_column("extension_id")
        batch.drop_column("kind")
