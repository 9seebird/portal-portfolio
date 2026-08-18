from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SeatResponse(BaseModel):
    """배치도 한 칸. 직원 정보는 조인해서 같이 내려준다(칸마다 다시 묻지 않게)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    floor: str
    row_idx: int
    col_idx: int
    row_span: int
    col_span: int
    kind: str
    label: Optional[str] = None
    team: Optional[str] = None
    marked: bool = False
    note: Optional[str] = None

    employee_id: Optional[UUID] = None
    employee_name: Optional[str] = None
    employee_no: Optional[str] = None
    employee_department: Optional[str] = None
    employee_position: Optional[str] = None
    employee_status: Optional[str] = None
    asset_count: int = 0
    # 내선번호. 사람에게 붙으므로 자리를 옮겨도 따라온다.
    employee_extension: Optional[str] = None
    # 직책자 여부. 직원 명단의 직책/직급을 보고 정한다(엑셀의 ● 은 안 쓴다).
    is_manager: bool = False


class SeatAssign(BaseModel):
    """자리에 사람 앉히기 / 비우기. employee_id 를 null 로 보내면 비운다."""

    employee_id: Optional[UUID] = None


class SeatUpdate(BaseModel):
    """칸 고치기. 좌표를 주면 그 자리로 옮긴다(배치 편집)."""

    kind: Optional[str] = None
    label: Optional[str] = None
    team: Optional[str] = None
    note: Optional[str] = None

    row_idx: Optional[int] = None
    col_idx: Optional[int] = None
    row_span: Optional[int] = None
    col_span: Optional[int] = None


class SeatCreate(BaseModel):
    """빈 격자에 새 칸을 만든다."""

    floor: str
    row_idx: int
    col_idx: int
    row_span: int = 1
    col_span: int = 1
    kind: str = "DESK"
    label: Optional[str] = None
    team: Optional[str] = None


class FloorSummary(BaseModel):
    floor: str
    rows: int
    cols: int
    desk_count: int
    seated_count: int
