from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class RentalContractCreate(BaseModel):
    asset_id: UUID
    vendor: str
    contract_no: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    monthly_fee: Decimal | None = None
    status: str = "ACTIVE"


class RentalContractUpdate(BaseModel):
    asset_id: UUID | None = None
    vendor: str | None = None
    contract_no: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    monthly_fee: Decimal | None = None
    status: str | None = None


class RentalContractResponse(RentalContractCreate):
    id: UUID

    class Config:
        from_attributes = True
