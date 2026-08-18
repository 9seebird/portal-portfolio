from sqlalchemy import Column, Date, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.db.base import Base


class LicenseAssignment(Base):
    """직원 한 명에게 라이선스 한 자리를 준 기록.

    자산(AssetAssignment)과 같은 방식이다.
      - 부여하면 행이 하나 생기고 released_at 이 비어 있다 (= 사용 중)
      - 회수하면 행을 지우지 않고 released_at 만 채운다 (= 이력이 남는다)

    이렇게 해두면 '지금 누가 무엇을 쓰는지' 와 '과거에 누가 썼는지' 를
    한 테이블로 답할 수 있다. 감사 대응에 그대로 쓰인다.

    라이선스 사용 수량(used_count)도 이 표를 세어서 구한다.
    엑셀에서 베껴온 고정 숫자를 쓰면 퇴사·회수가 반영되지 않아
    시간이 갈수록 실제보다 부풀어 오른다.
    """

    __tablename__ = "license_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    license_pool_id = Column(
        UUID(as_uuid=True),
        ForeignKey("license_pools.id"),
        nullable=False,
    )

    employee_id = Column(
        UUID(as_uuid=True),
        ForeignKey("employees.id"),
        nullable=False,
    )

    assigned_at = Column(Date)

    # 비어 있으면 '사용 중'. 회수하면 그때 날짜가 들어간다.
    released_at = Column(DateTime)

    # 회수 사유: OFFBOARD(퇴사) / MANUAL(개별 회수) 등
    release_reason = Column(String(20))

    note = Column(String(200))
