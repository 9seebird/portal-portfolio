from datetime import date
from uuid import UUID

from pydantic import BaseModel


class SoftwareProductCreate(BaseModel):
    name: str
    vendor: str | None = None
    license_type: str | None = None
    description: str | None = None


class SoftwareProductUpdate(BaseModel):
    name: str | None = None
    vendor: str | None = None
    license_type: str | None = None
    description: str | None = None


class SoftwareProductResponse(SoftwareProductCreate):
    id: UUID

    class Config:
        from_attributes = True


class LicensePoolCreate(BaseModel):
    software_id: UUID
    purchased_count: int = 0
    # 사용수량을 아직 집계하지 못한 라이선스는 null(미상)로 둔다.
    used_count: int | None = 0
    expire_date: date | None = None
    alert_days: int = 30


class LicensePoolUpdate(BaseModel):
    software_id: UUID | None = None
    purchased_count: int | None = None
    used_count: int | None = None
    expire_date: date | None = None
    alert_days: int | None = None


class LicensePoolResponse(LicensePoolCreate):
    id: UUID

    class Config:
        from_attributes = True


class SoftwareInstallationCreate(BaseModel):
    software_id: UUID
    asset_id: UUID
    installed_at: date | None = None


class SoftwareInstallationResponse(SoftwareInstallationCreate):
    id: UUID

    class Config:
        from_attributes = True
