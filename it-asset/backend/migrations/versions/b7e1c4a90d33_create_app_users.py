"""이 앱에 들어온 사람과 화면 권한 표를 만든다.

포털은 "자산관리를 쓸 수 있나"까지만 정한다. 그 안에서 누가 어느 화면을
보는지는 이 앱에만 있는 이야기라 여기에 둔다.

user_id 는 포털 아이디다. 이 앱에는 계정이 없으므로 그것이 곧 열쇠다.
"""

import sqlalchemy as sa
from alembic import op

revision = "b7e1c4a90d33"
down_revision = "a3e6d71c845f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 앱이 뜰 때 이 표를 스스로 만든다 (app/main.py 의 ensure_permission_table).
    # 배포하면서 마이그레이션을 빠뜨려도 안 깨지게 해 둔 장치인데, 그 바람에
    # 여기 왔을 때는 표가 이미 있을 수 있다. 그때 그냥 만들려 들면
    # "table app_users already exists" 로 배포가 멈춘다.
    #
    # 이미 있으면 할 일이 없다. 기록만 앞으로 넘긴다.
    if sa.inspect(op.get_bind()).has_table("app_users"):
        return

    op.create_table(
        "app_users",
        sa.Column("user_id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("dept", sa.String(length=100), nullable=False, server_default=""),
        # 볼 수 있는 화면을 쉼표로 이어 둔다 ("employees,seats").
        # 비어 있으면 기본값을 쓴다 — 사람마다 정해 주지 않아도 돌아간다.
        sa.Column("views", sa.Text(), nullable=False, server_default=""),
        sa.Column("first_seen", sa.TIMESTAMP(timezone=True),
                  server_default=sa.func.now()),
        sa.Column("last_seen", sa.TIMESTAMP(timezone=True),
                  server_default=sa.func.now()),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("app_users"):
        op.drop_table("app_users")
