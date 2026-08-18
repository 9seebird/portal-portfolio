from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from app.db.base import Base


class IPAssignment(Base):
    __tablename__ = "ip_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # 이 IP 가 무엇에 붙었는지.
    #   NETWORK : PC·서버 등 자산에 붙은 IP  -> asset_id
    #   PHONE   : 전화기에 붙은 IP           -> extension_id
    # 전화기는 자산으로 등록하지 않으므로(대수가 많고 사양도 필요 없다)
    # 내선번호를 전화기의 신원으로 삼는다.
    kind = Column(String(20), nullable=False, default="NETWORK")

    asset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("assets.id"),
        nullable=True
    )

    extension_id = Column(
        UUID(as_uuid=True),
        ForeignKey("extensions.id", ondelete="SET NULL"),
        nullable=True
    )

    ip_range_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ip_ranges.id"),
        nullable=True
    )

    ip_address = Column(
        String(50),
        nullable=False
    )

    hostname = Column(
        String(100)
    )

    mac_address = Column(
        String(100)
    )

    status = Column(
        String(20),
        default="USED"
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )
