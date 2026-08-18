from sqlalchemy import Column, Integer, Date, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.db.base import Base


class LicensePool(Base):
    __tablename__ = "license_pools"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    software_id = Column(
        UUID(as_uuid=True),
        ForeignKey("software_products.id"),
        nullable=False
    )

    purchased_count = Column(Integer)

    used_count = Column(Integer)

    expire_date = Column(Date)

    alert_days = Column(Integer, default=30)