from sqlalchemy import Column, String, Text
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.db.base import Base


class SoftwareProduct(Base):
    __tablename__ = "software_products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    name = Column(String(255), nullable=False)

    vendor = Column(String(255))

    license_type = Column(String(50))

    description = Column(Text)