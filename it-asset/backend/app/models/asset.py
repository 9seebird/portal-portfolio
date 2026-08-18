from sqlalchemy import Column, String, Integer, Date, Text, TIMESTAMP
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.db.base import Base


class Asset(Base):
    __tablename__ = "assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    asset_no = Column(String(50), unique=True)

    # 엑셀 PC대장의 "라벨 번호" (기기에 붙은 스티커 번호)
    label_no = Column(String(50))

    # 엑셀 재동기화용 자연키. 자산번호가 없는 행도 안정적으로 매칭하기 위해 사용한다.
    source_key = Column(String(64), unique=True)

    asset_type = Column(String(30))

    manufacturer = Column(String(100))
    model = Column(String(255))
    serial_no = Column(String(255))

    cpu = Column(String(255))

    memory_gb = Column(Integer)
    storage_gb = Column(Integer)

    os = Column(String(100))

    purchase_type = Column(String(20))

    purchase_date = Column(Date)

    rental_vendor = Column(String(100))
    rental_end_date = Column(Date)

    # 갓 등록한 자산은 아직 아무도 안 갖고 있으니 '보관'이다.
    # IN_USE 로 두면 '사용 중인데 사용자가 없는' 자산이 되어
    # 지급하려고 보관 목록을 열어도 거기 없다 (등록해놓고 못 찾게 된다).
    status = Column(String(20), default="STORAGE")

    qr_code = Column(String(255))

    notes = Column(Text)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
