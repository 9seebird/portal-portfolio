from sqlalchemy import Column, Date, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.db.base import Base


class SoftwareInstallation(Base):
    __tablename__ = "software_installations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    software_id = Column(
        UUID(as_uuid=True),
        ForeignKey("software_products.id"),
        nullable=False
    )

    asset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("assets.id"),
        nullable=False
    )

    installed_at = Column(Date)