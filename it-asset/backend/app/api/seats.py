"""사무실 배치도.

엑셀로 관리하던 좌석 배치를 그대로 격자로 옮긴 것이다.
자리(DESK)에 직원을 연결해두면, 배치도에서 자리를 눌러
그 사람의 자산·IP·라이선스를 바로 확인할 수 있다.

  층 목록   GET   /seats/floors
  한 층     GET   /seats?floor=3층
  사람 지정 PUT   /seats/{id}/employee    (null 이면 자리 비우기)
  칸 고치기 PATCH /seats/{id}
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.enums import is_manager_title
from app.core.security import get_current_user
from app.api.permissions import require_view
from app.db.database import get_db
from app.models.asset_assignment import AssetAssignment
from app.models.employee import Employee
from app.models.extension import Extension
from app.models.seat import Seat
from app.schemas.seat import (
    FloorSummary,
    SeatAssign,
    SeatCreate,
    SeatResponse,
    SeatUpdate,
)

router = APIRouter(
    prefix="/seats",
    tags=["Seats"],
    dependencies=[Depends(get_current_user)],
)

VALID_KINDS = ("DESK", "ROOM", "LABEL")


def _check_free(db: Session, floor: str, row: int, col: int,
                row_span: int, col_span: int, exclude_id=None) -> None:
    """그 자리에 이미 다른 칸이 있으면 막는다.

    칸은 병합될 수 있어서(회의실 3x4 등) 왼쪽 위 좌표만 비교하면 겹침을 놓친다.
    두 사각형이 겹치는지 직접 본다. DB 의 유니크 제약은 왼쪽 위만 막아준다.
    """
    if row < 1 or col < 1:
        raise HTTPException(status_code=400, detail="좌표는 1부터입니다.")
    if row_span < 1 or col_span < 1:
        raise HTTPException(status_code=400, detail="칸 크기는 1 이상이어야 합니다.")

    query = db.query(Seat).filter(Seat.floor == floor)
    if exclude_id is not None:
        query = query.filter(Seat.id != exclude_id)

    for other in query.all():
        overlap_rows = (row < other.row_idx + other.row_span
                        and other.row_idx < row + row_span)
        overlap_cols = (col < other.col_idx + other.col_span
                        and other.col_idx < col + col_span)
        if overlap_rows and overlap_cols:
            what = other.employee_id and "사람이 앉은 자리" or (other.label or "다른 칸")
            raise HTTPException(
                status_code=409,
                detail=f"그 자리에는 이미 '{what}' 이(가) 있습니다.",
            )


def _extensions(db: Session) -> dict:
    """직원별 내선번호. 자리마다 따로 조회하면 N+1 이라 한 번에 모은다."""
    return {
        row.employee_id: row.number
        for row in db.query(Extension).filter(Extension.employee_id.isnot(None)).all()
    }


def _asset_counts(db: Session) -> dict:
    """직원별 '지금 보유 중인' 자산 수. 자리마다 세면 N+1 이라 한 번에 모은다."""
    rows = (
        db.query(AssetAssignment.employee_id, func.count(AssetAssignment.id))
        .filter(AssetAssignment.returned_at.is_(None))
        .group_by(AssetAssignment.employee_id)
        .all()
    )
    return {employee_id: count for employee_id, count in rows}


def _to_response(seat: Seat, employee: Employee | None, asset_count: int,
                 extension: str | None = None) -> SeatResponse:
    return SeatResponse(
        id=seat.id,
        floor=seat.floor,
        row_idx=seat.row_idx,
        col_idx=seat.col_idx,
        row_span=seat.row_span,
        col_span=seat.col_span,
        kind=seat.kind,
        label=seat.label,
        team=seat.team,
        marked=seat.marked,
        note=seat.note,
        employee_id=seat.employee_id,
        employee_name=employee.name if employee else None,
        employee_no=employee.emp_no if employee else None,
        employee_department=employee.department if employee else None,
        employee_position=employee.position if employee else None,
        employee_status=employee.status if employee else None,
        asset_count=asset_count,
        employee_extension=extension,
        is_manager=is_manager_title(employee.position, employee.rank) if employee else False,
    )


@router.get("/floors", response_model=list[FloorSummary])
def list_floors(db: Session = Depends(get_db)):
    """층 목록과 격자 크기. 화면이 몇 칸짜리 표를 그릴지 이걸로 정한다."""
    rows = (
        db.query(
            Seat.floor,
            func.max(Seat.row_idx + Seat.row_span - 1),
            func.max(Seat.col_idx + Seat.col_span - 1),
            func.count(Seat.id).filter(Seat.kind == "DESK"),
            func.count(Seat.id).filter(Seat.employee_id.isnot(None)),
        )
        .group_by(Seat.floor)
        .order_by(Seat.floor)
        .all()
    )
    return [
        FloorSummary(floor=f, rows=r or 0, cols=c or 0, desk_count=d or 0, seated_count=s or 0)
        for f, r, c, d, s in rows
    ]


@router.get("", response_model=list[SeatResponse])
@router.get("/", response_model=list[SeatResponse])
def list_seats(
    floor: str | None = Query(None, description="비우면 전체 층"),
    db: Session = Depends(get_db),
):
    # 자리 + 직원을 조인 한 번으로. LEFT JOIN 이라 빈 자리도 그대로 나온다.
    query = db.query(Seat, Employee).outerjoin(Employee, Employee.id == Seat.employee_id)
    if floor:
        query = query.filter(Seat.floor == floor)
    pairs = query.order_by(Seat.floor, Seat.row_idx, Seat.col_idx).all()

    counts = _asset_counts(db)
    extensions = _extensions(db)
    return [
        _to_response(seat, employee, counts.get(seat.employee_id, 0),
                     extensions.get(seat.employee_id))
        for seat, employee in pairs
    ]


@router.post("", response_model=SeatResponse)
@router.post("/", response_model=SeatResponse)
def create_seat(
    payload: SeatCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("seats")),
):
    """빈 격자에 새 칸을 만든다. 책상이 늘어났을 때 쓴다."""
    if payload.kind not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"종류는 {VALID_KINDS} 중 하나여야 합니다.")

    _check_free(db, payload.floor, payload.row_idx, payload.col_idx,
                payload.row_span, payload.col_span)

    seat = Seat(**payload.model_dump())
    db.add(seat)
    db.commit()
    db.refresh(seat)
    return _to_response(seat, None, 0)


@router.put("/{seat_id}/employee", response_model=SeatResponse)
def assign_employee(
    seat_id: UUID,
    payload: SeatAssign,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("seats")),
):
    seat = db.query(Seat).filter(Seat.id == seat_id).first()
    if not seat:
        raise HTTPException(status_code=404, detail="자리를 찾을 수 없습니다.")
    if seat.kind != "DESK":
        raise HTTPException(
            status_code=400,
            detail="사람이 앉는 자리가 아닙니다. 먼저 종류를 '자리'로 바꾸세요.",
        )

    # 비우기
    if payload.employee_id is None:
        seat.employee_id = None
        db.commit()
        db.refresh(seat)
        return _to_response(seat, None, 0)

    employee = db.query(Employee).filter(Employee.id == payload.employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="직원을 찾을 수 없습니다.")
    if employee.status == "INACTIVE":
        raise HTTPException(status_code=400, detail="퇴사한 직원은 자리에 앉힐 수 없습니다.")

    # 한 사람이 두 자리를 차지하지 않게. DB 제약도 걸려 있지만
    # 여기서 막아야 "어느 자리에 이미 있는지"를 알려줄 수 있다.
    taken = (
        db.query(Seat)
        .filter(Seat.employee_id == employee.id, Seat.id != seat.id)
        .first()
    )
    if taken:
        raise HTTPException(
            status_code=409,
            detail=f"{employee.name} 님은 이미 {taken.floor} 자리에 배치되어 있습니다. "
                   f"그 자리를 먼저 비우세요.",
        )

    seat.employee_id = employee.id
    db.commit()
    db.refresh(seat)
    return _to_response(seat, employee, _asset_counts(db).get(employee.id, 0),
                        _extensions(db).get(employee.id))


@router.patch("/{seat_id}", response_model=SeatResponse)
def update_seat(
    seat_id: UUID,
    payload: SeatUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("seats")),
):
    seat = db.query(Seat).filter(Seat.id == seat_id).first()
    if not seat:
        raise HTTPException(status_code=404, detail="자리를 찾을 수 없습니다.")

    data = payload.model_dump(exclude_unset=True)
    if "kind" in data and data["kind"] not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"종류는 {VALID_KINDS} 중 하나여야 합니다.")

    # 좌표나 크기가 왔으면 옮기는 것이다. 겹치는지 먼저 본다.
    if any(key in data for key in ("row_idx", "col_idx", "row_span", "col_span")):
        _check_free(
            db, seat.floor,
            data.get("row_idx", seat.row_idx),
            data.get("col_idx", seat.col_idx),
            data.get("row_span", seat.row_span),
            data.get("col_span", seat.col_span),
            exclude_id=seat.id,
        )
    # 자리가 아니게 바꾸면 앉아 있던 사람은 떼어낸다. 안 그러면
    # 화면에 안 보이는 곳에 사람이 묶여 있게 된다.
    if data.get("kind") in ("ROOM", "LABEL"):
        seat.employee_id = None

    for key, value in data.items():
        setattr(seat, key, value)

    db.commit()
    db.refresh(seat)
    employee = (
        db.query(Employee).filter(Employee.id == seat.employee_id).first()
        if seat.employee_id
        else None
    )
    return _to_response(seat, employee, _asset_counts(db).get(seat.employee_id, 0),
                        _extensions(db).get(seat.employee_id))


@router.delete("/{seat_id}")
def delete_seat(
    seat_id: UUID,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("seats")),
):
    """칸 자체를 없앤다.

    엑셀에서 테두리만 있는 칸을 '빈 책상'으로 읽어오다 보면
    책상이 아닌 네모까지 들어올 수 있다. 그런 칸을 화면에서 지우는 용도다.
    사람이 앉아 있으면 먼저 비우게 한다 — 실수로 배치를 날리지 않도록.
    """
    seat = db.query(Seat).filter(Seat.id == seat_id).first()
    if not seat:
        raise HTTPException(status_code=404, detail="자리를 찾을 수 없습니다.")
    if seat.employee_id:
        raise HTTPException(
            status_code=409,
            detail="사람이 앉아 있는 자리입니다. 먼저 자리를 비우세요.",
        )

    db.delete(seat)
    db.commit()
    return {"message": "seat deleted"}
