from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AssetAssignCreate(BaseModel):
    employee_id: UUID


class AssetAssignmentCreate(BaseModel):
    asset_id: UUID
    employee_id: UUID


class AssetAssignmentResponse(BaseModel):
    id: UUID
    asset_id: UUID
    employee_id: UUID

    assigned_at: datetime | None = None
    returned_at: datetime | None = None

    class Config:
        from_attributes = True
