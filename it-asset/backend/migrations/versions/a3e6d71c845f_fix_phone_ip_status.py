"""내선에 붙어 있는 전화기 IP 의 상태를 '사용 중'으로 맞춘다.

상태가 FREE 인 채로 내선에 붙어 있으면 화면마다 다르게 보였다.
IP 관리에는 나오는데 내선 관리·직원별 현황·배치도에는 안 나오는 식이다.

앞으로는 API 가 전화기 IP 를 늘 USED 로 강제하므로 이런 줄이 다시 생기지 않는다.
여기서는 이미 생겨 버린 줄만 바로잡는다.
"""

from alembic import op

revision = "a3e6d71c845f"
down_revision = "f8d530c9e1b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE ip_assignments SET status = 'USED' "
        "WHERE kind = 'PHONE' AND extension_id IS NOT NULL AND status <> 'USED'"
    )


def downgrade() -> None:
    # 되돌릴 것이 없다. 원래 상태가 무엇이었는지 알 수 없고,
    # 알더라도 그 상태가 잘못된 것이었다.
    pass
