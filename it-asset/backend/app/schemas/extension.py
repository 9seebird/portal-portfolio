from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class ExtensionResponse(BaseModel):
    """내선번호 한 줄. 쓰는 사람 정보는 조인해서 같이 내려준다."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    zone: Optional[str] = None
    note: Optional[str] = None

    employee_id: Optional[UUID] = None
    employee_name: Optional[str] = None
    employee_no: Optional[str] = None
    employee_department: Optional[str] = None
    employee_status: Optional[str] = None
    # 그 내선에 붙은 전화기 IP (ip_assignments 에서 조인)
    ip_address: Optional[str] = None


def _clean_number(value: str) -> str:
    """'1234 ' 나 '12-34' 처럼 들어와도 같은 번호로 취급되게 다듬는다.

    공백만 지우고 나머지는 그대로 둔다 — '#701' 같은 번호도 있어서
    숫자만 남기면 오히려 잘못 뭉친다.
    """
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError("내선번호는 비울 수 없습니다.")
    return cleaned


class ExtensionCreate(BaseModel):
    number: str
    zone: Optional[str] = None
    note: Optional[str] = None
    employee_id: Optional[UUID] = None

    @field_validator("number")
    @classmethod
    def _number(cls, value: str) -> str:
        return _clean_number(value)


class ExtensionUpdate(BaseModel):
    number: Optional[str] = None
    zone: Optional[str] = None
    note: Optional[str] = None

    @field_validator("number")
    @classmethod
    def _number(cls, value):
        return _clean_number(value) if value is not None else value


class ExtensionAssign(BaseModel):
    """번호에 사람 붙이기 / 떼기. employee_id 를 null 로 보내면 비운다."""

    employee_id: Optional[UUID] = None
