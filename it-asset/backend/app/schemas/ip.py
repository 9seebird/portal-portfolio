from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class IPRangeCreate(BaseModel):
    name: str
    # NETWORK(PC·서버) / PHONE(전화기)
    kind: str = "NETWORK"
    start_ip: str
    end_ip: str
    vlan: str | None = None
    gateway: str | None = None
    dns: str | None = None
    description: str | None = None


class IPRangeUpdate(BaseModel):
    name: str | None = None
    kind: str | None = None
    start_ip: str | None = None
    end_ip: str | None = None
    vlan: str | None = None
    gateway: str | None = None
    dns: str | None = None
    description: str | None = None


class IPRangeResponse(IPRangeCreate):
    id: UUID

    class Config:
        from_attributes = True


class IPAssignmentCreate(BaseModel):
    """IP 하나를 무언가에 붙인다.

    kind 에 따라 붙는 대상이 다르다.
      NETWORK : asset_id 가 있어야 한다 (PC·서버)
      PHONE   : extension_id 가 있어야 한다 (전화기 = 내선번호)
    """

    kind: str = "NETWORK"
    asset_id: UUID | None = None
    extension_id: UUID | None = None
    ip_range_id: UUID | None = None
    ip_address: str
    hostname: str | None = None
    mac_address: str | None = None
    status: str = "USED"


class IPAssignmentUpdate(BaseModel):
    kind: str | None = None
    asset_id: UUID | None = None
    extension_id: UUID | None = None
    ip_range_id: UUID | None = None
    ip_address: str | None = None
    hostname: str | None = None
    mac_address: str | None = None
    status: str | None = None


class IPAssignmentResponse(IPAssignmentCreate):
    id: UUID
    created_at: datetime | None = None
    # 화면에서 바로 쓰라고 붙여 보낸다 (표마다 다시 조회하지 않게)
    asset_no: str | None = None
    extension_number: str | None = None
    employee_name: str | None = None
    employee_department: str | None = None

    class Config:
        from_attributes = True
