"""내선번호 표를 만든다.

번호는 사람에게 붙는다(자리를 옮겨도 따라간다). 그래서 employee_id 를 두고
한 사람에 하나만 붙도록 유니크를 건다 — NULL 은 여러 개 허용되므로
아직 아무도 안 쓰는 빈 번호는 얼마든지 있어도 된다.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e7c419b8d2a5"
down_revision = "d5a2c81b3f40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "extensions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("number", sa.String(length=20), nullable=False),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employees.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("zone", sa.String(length=50)),
        sa.Column("note", sa.String(length=200)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("number", name="uq_extensions_number"),
        sa.UniqueConstraint("employee_id", name="uq_extensions_employee"),
    )
    op.create_index("ix_extensions_number", "extensions", ["number"])


def downgrade() -> None:
    op.drop_index("ix_extensions_number", table_name="extensions")
    op.drop_table("extensions")
