"""내선번호.

IP 관리와 같은 결로 다루되, 붙는 대상이 다르다.
IP 는 장비(자산)에 붙고, 내선은 사람에게 붙는다 — 자리를 옮겨도 번호는 따라간다.

  목록      GET    /extensions
  등록      POST   /extensions
  고치기    PATCH  /extensions/{id}
  사람 지정 PUT    /extensions/{id}/employee   (null 이면 비우기)
  지우기    DELETE /extensions/{id}
  자료 넣기 POST   /extensions/import          (엑셀·CSV 올리기)
"""

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.api.permissions import require_view
from app.db.database import get_db
from app.models.employee import Employee
from app.models.extension import Extension
from app.models.ip_assignment import IPAssignment
from app.services import extension_import
from app.schemas.extension import (
    ExtensionAssign,
    ExtensionCreate,
    ExtensionResponse,
    ExtensionUpdate,
)

router = APIRouter(
    prefix="/extensions",
    tags=["Extensions"],
    dependencies=[Depends(get_current_user)],
)


def _phone_ips(db: Session) -> dict:
    """내선별 전화기 IP. 번호마다 따로 조회하면 N+1 이라 한 번에 모은다."""
    # 상태로 거르지 않는다. 내선에 붙어 있으면 그게 그 번호의 전화기 IP 다.
    # 거르면 IP 관리에는 보이는데 여기서는 안 보이는 일이 생긴다.
    rows = db.query(IPAssignment).filter(
        IPAssignment.kind == "PHONE",
        IPAssignment.extension_id.isnot(None),
    ).all()
    return {row.extension_id: row.ip_address for row in rows}


def _to_response(extension: Extension, employee: Employee | None,
                 ip_address: str | None = None) -> ExtensionResponse:
    return ExtensionResponse(
        id=extension.id,
        number=extension.number,
        zone=extension.zone,
        note=extension.note,
        employee_id=extension.employee_id,
        employee_name=employee.name if employee else None,
        employee_no=employee.emp_no if employee else None,
        employee_department=employee.department if employee else None,
        employee_status=employee.status if employee else None,
        ip_address=ip_address,
    )


def _get(db: Session, extension_id: UUID) -> Extension:
    extension = db.query(Extension).filter(Extension.id == extension_id).first()
    if not extension:
        raise HTTPException(status_code=404, detail="내선번호를 찾을 수 없습니다.")
    return extension


def _check_number_free(db: Session, number: str, exclude_id: UUID | None = None) -> None:
    query = db.query(Extension).filter(Extension.number == number)
    if exclude_id is not None:
        query = query.filter(Extension.id != exclude_id)
    if query.first():
        raise HTTPException(status_code=409, detail=f"내선번호 {number} 는 이미 등록돼 있습니다.")


def _sort_key(number: str):
    """번호를 사람 눈에 맞게 정렬한다.

    문자열로 두면 '1000' 이 '900' 보다 앞에 온다. 숫자로만 된 번호는
    숫자로 비교하고, '#701' 같은 것은 뒤로 보낸다.
    """
    digits = "".join(ch for ch in number if ch.isdigit())
    return (0, int(digits), number) if digits and number.isdigit() else (1, 0, number)


@router.get("", response_model=list[ExtensionResponse])
@router.get("/", response_model=list[ExtensionResponse])
def list_extensions(
    q: str | None = Query(None, description="번호·이름·부서로 거르기"),
    free_only: bool = Query(False, description="아직 아무도 안 쓰는 번호만"),
    db: Session = Depends(get_db),
):
    # 번호 + 사람을 조인 한 번으로. 번호마다 사람을 따로 조회하면 N+1 이 된다.
    pairs = (
        db.query(Extension, Employee)
        .outerjoin(Employee, Employee.id == Extension.employee_id)
        .all()
    )

    if free_only:
        pairs = [(e, emp) for e, emp in pairs if e.employee_id is None]

    if q:
        needle = q.strip().lower()
        pairs = [
            (e, emp) for e, emp in pairs
            if any(needle in str(v).lower() for v in (
                e.number, e.zone, e.note,
                emp.name if emp else None,
                emp.emp_no if emp else None,
                emp.department if emp else None,
            ) if v)
        ]

    pairs.sort(key=lambda pair: _sort_key(pair[0].number))
    ips = _phone_ips(db)
    return [_to_response(e, emp, ips.get(e.id)) for e, emp in pairs]


@router.post("", response_model=ExtensionResponse)
@router.post("/", response_model=ExtensionResponse)
def create_extension(
    payload: ExtensionCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("extensions")),
):
    _check_number_free(db, payload.number)

    employee = None
    if payload.employee_id:
        employee = _validate_employee(db, payload.employee_id)

    extension = Extension(
        number=payload.number,
        zone=payload.zone,
        note=payload.note,
        employee_id=payload.employee_id,
    )
    db.add(extension)
    db.commit()
    db.refresh(extension)
    return _to_response(extension, employee, _phone_ips(db).get(extension.id))


def _validate_employee(db: Session, employee_id: UUID, exclude_extension=None) -> Employee:
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="직원을 찾을 수 없습니다.")
    if employee.status == "INACTIVE":
        raise HTTPException(status_code=400, detail="퇴사한 직원에게는 번호를 줄 수 없습니다.")

    # 한 사람에 번호 하나. DB 제약도 있지만 여기서 막아야
    # "이미 어느 번호를 쓰고 있는지"를 알려줄 수 있다.
    query = db.query(Extension).filter(Extension.employee_id == employee_id)
    if exclude_extension is not None:
        query = query.filter(Extension.id != exclude_extension)
    taken = query.first()
    if taken:
        raise HTTPException(
            status_code=409,
            detail=f"{employee.name} 님은 이미 내선 {taken.number} 를 쓰고 있습니다. "
                   f"그 번호를 먼저 비우세요.",
        )
    return employee


# 주의: 이 경로는 /{extension_id} 보다 먼저 선언해야 한다.
# 뒤에 두면 'import' 를 id 로 읽어서 422 가 난다.
@router.post("/import")
async def import_extensions(
    file: UploadFile = File(..., description="엑셀(.xlsx) 또는 CSV"),
    apply: bool = Form(False, description="false 면 미리보기만 한다"),
    overwrite: bool = Form(False, description="이미 있는 번호도 파일 내용으로 덮어쓴다"),
    db: Session = Depends(get_db),
    _admin=Depends(require_view("extensions")),
):
    """엑셀·CSV 를 올려서 내선번호를 한꺼번에 넣는다.

    기본은 미리보기다. 무엇이 들어가고 무엇이 왜 빠지는지 먼저 보여주고,
    apply=true 로 한 번 더 불러야 실제로 들어간다 — 남의 자료를 한 방에
    갈아엎는 일은 없어야 하기 때문이다.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="파일이 너무 큽니다 (5MB 까지).")

    try:
        rows = extension_import.read_table(data, file.filename or "")
        planned = extension_import.plan(db, rows, overwrite=overwrite)
    except extension_import.ImportError_ as error:
        raise HTTPException(status_code=400, detail=str(error))

    result = {
        "applied": False,
        "columns": planned["columns"],
        "new": planned["new"],
        "update": planned["update"],
        "skipped": planned["skipped"],
    }
    if not apply:
        return result

    try:
        counts = extension_import.apply_plan(db, planned)
    except Exception:
        db.rollback()
        raise
    return {**result, "applied": True, **counts}


@router.put("/{extension_id}/employee", response_model=ExtensionResponse)
def assign_employee(
    extension_id: UUID,
    payload: ExtensionAssign,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("extensions")),
):
    extension = _get(db, extension_id)

    if payload.employee_id is None:
        extension.employee_id = None
        db.commit()
        db.refresh(extension)
        return _to_response(extension, None, _phone_ips(db).get(extension.id))

    employee = _validate_employee(db, payload.employee_id, exclude_extension=extension.id)
    extension.employee_id = employee.id
    db.commit()
    db.refresh(extension)
    return _to_response(extension, employee, _phone_ips(db).get(extension.id))


@router.patch("/{extension_id}", response_model=ExtensionResponse)
def update_extension(
    extension_id: UUID,
    payload: ExtensionUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("extensions")),
):
    extension = _get(db, extension_id)
    data = payload.model_dump(exclude_unset=True)

    if "number" in data and data["number"] != extension.number:
        _check_number_free(db, data["number"], exclude_id=extension.id)

    for key, value in data.items():
        setattr(extension, key, value)

    db.commit()
    db.refresh(extension)
    employee = (
        db.query(Employee).filter(Employee.id == extension.employee_id).first()
        if extension.employee_id
        else None
    )
    return _to_response(extension, employee, _phone_ips(db).get(extension.id))


@router.delete("/{extension_id}")
def delete_extension(
    extension_id: UUID,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("extensions")),
):
    """번호 자체를 목록에서 없앤다.

    쓰는 사람이 있으면 먼저 비우게 한다 — 잘못 지우면 누가 쓰던 번호였는지
    되짚을 방법이 없다.
    """
    extension = _get(db, extension_id)
    if extension.employee_id:
        raise HTTPException(
            status_code=409,
            detail="쓰는 사람이 있는 번호입니다. 먼저 비우세요.",
        )

    # 이 내선에 붙어 있던 전화기 IP 는 같이 놓아준다. 안 그러면
    # 어디에도 안 보이는 유령 IP 가 남아 그 주소를 다시 못 쓴다.
    db.query(IPAssignment).filter(
        IPAssignment.extension_id == extension.id,
    ).delete(synchronize_session=False)

    db.delete(extension)
    db.commit()
    return {"message": "extension deleted"}
