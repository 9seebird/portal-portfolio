import uuid

from sqlalchemy import Column, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class IPRange(Base):
    __tablename__ = "ip_ranges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    # NETWORK(PC·서버) / PHONE(전화기). 빈 IP 를 종류별로 뽑을 때 쓴다.
    kind = Column(String(20), nullable=False, default="NETWORK")
    start_ip = Column(String(50), nullable=False)
    end_ip = Column(String(50), nullable=False)
    vlan = Column(String(50))
    gateway = Column(String(50))
    dns = Column(String(50))
    description = Column(Text)
