import uuid

from sqlalchemy import Column, ForeignKey, String, TIMESTAMP, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.db.base import Base


class Extension(Base):
    """내선번호.

    IP 와 비슷하게 '번호 하나에 쓰는 사람 하나'로 관리한다. 다만 IP 는 장비(자산)에
    붙는 반면 내선은 사람에게 붙인다 — 자리를 옮겨도 번호는 그 사람을 따라간다.

    employee_id 가 비어 있으면 아직 아무도 안 쓰는 번호(빈 번호)다.
    """

    __tablename__ = "extensions"
    __table_args__ = (
        # 같은 번호가 두 번 등록되면 어느 쪽이 진짜인지 알 수 없다
        UniqueConstraint("number", name="uq_extensions_number"),
        # 한 사람에 번호 하나. NULL 은 여러 개 허용되므로 빈 번호는 얼마든지 있어도 된다.
        UniqueConstraint("employee_id", name="uq_extensions_employee"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # '1234' 처럼 숫자만 오는 게 보통이지만 '#701' 같은 것도 있어서 문자열로 둔다
    number = Column(String(20), nullable=False)

    employee_id = Column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )

    # 어느 층/구역 번호인지 (예: '3층', '지원본부'). 목록을 묶어 보는 데 쓴다.
    zone = Column(String(50))
    note = Column(String(200))

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
