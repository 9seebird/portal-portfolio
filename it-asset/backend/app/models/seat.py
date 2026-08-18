import uuid

from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class Seat(Base):
    """사무실 배치도의 한 칸.

    엑셀 배치도를 그대로 옮긴 격자다. row_idx/col_idx 는 층 안에서의 좌표이고
    row_span/col_span 은 엑셀 병합셀에 해당한다(회의실처럼 여러 칸을 차지하는 공간).

    kind
      DESK  : 사람이 앉는 자리. employee_id 로 직원과 연결된다.
      ROOM  : 회의실·탕비실·창고처럼 이름만 있는 공간.
      LABEL : '재무팀' 같은 구역 표시 글자.
    """

    __tablename__ = "seats"
    __table_args__ = (
        # 한 층의 같은 칸에 두 개가 겹치지 않게
        UniqueConstraint("floor", "row_idx", "col_idx", name="uq_seats_floor_cell"),
        # 한 사람이 두 자리에 앉을 수 없다. NULL 은 여러 개 허용되므로
        # 빈 자리는 얼마든지 있어도 된다.
        UniqueConstraint("employee_id", name="uq_seats_employee"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    floor = Column(String(20), nullable=False)
    row_idx = Column(Integer, nullable=False)
    col_idx = Column(Integer, nullable=False)
    row_span = Column(Integer, nullable=False, default=1)
    col_span = Column(Integer, nullable=False, default=1)

    kind = Column(String(10), nullable=False, default="DESK")
    # DESK 면 엑셀에 적혀 있던 이름(직원 연결 전 표시용), ROOM/LABEL 이면 공간 이름
    label = Column(String(100))
    team = Column(String(50))
    # 엑셀에 (●) 로 표시돼 있던 자리
    marked = Column(Boolean, nullable=False, default=False)

    employee_id = Column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )

    note = Column(String(200))
