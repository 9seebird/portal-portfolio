from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class LicenseAssignmentCreate(BaseModel):
    """라이선스 부여."""
    license_pool_id: UUID
    employee_id: UUID
    assigned_at: date | None = None
    note: str | None = None


class LicenseAssignmentRelease(BaseModel):
    """라이선스 회수. 퇴사와 무관하게 개별 회수할 때 쓴다."""
    note: str | None = None


class LicenseAssignmentResponse(BaseModel):
    id: UUID
    license_pool_id: UUID
    employee_id: UUID
    assigned_at: date | None = None
    released_at: datetime | None = None
    release_reason: str | None = None
    note: str | None = None

    # 화면에서 바로 보여주기 위한 값
    employee_name: str | None = None
    software_name: str | None = None

    class Config:
        from_attributes = True


class LicenseUsage(BaseModel):
    """라이선스별 실시간 보유/사용 현황."""
    license_pool_id: UUID
    software_id: UUID
    software_name: str
    purchased_count: int | None = None
    used_count: int          # 실제 부여 건수를 센 값 (저장된 숫자가 아님)
    available_count: int | None = None
    is_over_allocated: bool
    expire_date: date | None = None
