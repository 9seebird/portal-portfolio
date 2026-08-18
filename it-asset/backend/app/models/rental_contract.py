import uuid

from sqlalchemy import Column, Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class RentalContract(Base):
    __tablename__ = "rental_contracts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    vendor = Column(String(100), nullable=False)
    contract_no = Column(String(100))
    start_date = Column(Date)
    end_date = Column(Date)
    monthly_fee = Column(Numeric(12, 2))
    status = Column(String(20), default="ACTIVE")
