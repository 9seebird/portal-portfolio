"""라이선스 부여 / 회수.

자산(AssetAssignment)과 같은 방식으로 동작한다.
  부여  POST /license-assignments
  회수  POST /license-assignments/{id}/release
  현황  GET  /license-assignments?employee_id=...&active_only=true

사용 수량은 이 표를 세어서 구한다(GET /license-assignments/usage).
license_pools.used_count 는 엑셀에서 베껴온 초기값이라
퇴사·회수가 반영되지 않는다. 화면에는 세어서 구한 값을 쓴다.
"""

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.api.permissions import require_view
from app.db.database import get_db
from app.models.employee import Employee
from app.models.license_assignment import LicenseAssignment
from app.models.license_pool import LicensePool
from app.models.software_product import SoftwareProduct
from app.schemas.license_assignment import (
    LicenseAssignmentCreate,
    LicenseAssignmentRelease,
    LicenseAssignmentResponse,
    LicenseUsage,
)

router = APIRouter(
    prefix="/license-assignments",
    tags=["License Assignments"],
    dependencies=[Depends(get_current_user)],
)


# 성능 주의: 처음 버전은 행마다 직원/소프트웨어를 따로 조회했다(N+1).
# 127건 기준 요청 한 번에 쿼리 255개가 나가 화면이 눈에 띄게 느렸다.
# 지금은 조인 한 번으로 같은 정보를 가져온다.

def _joined(db: Session):
    """부여 + 직원 이름 + 소프트웨어 이름을 쿼리 한 번에."""
    return (
        db.query(LicenseAssignment, Employee.name, SoftwareProduct.name)
        .join(Employee, Employee.id == LicenseAssignment.employee_id)
        .join(LicensePool, LicensePool.id == LicenseAssignment.license_pool_id)
        .join(SoftwareProduct, SoftwareProduct.id == LicensePool.software_id)
    )


def _to_response(a: LicenseAssignment, employee_name, software_name) -> LicenseAssignmentResponse:
    return LicenseAssignmentResponse(
        id=a.id,
        license_pool_id=a.license_pool_id,
        employee_id=a.employee_id,
        assigned_at=a.assigned_at,
        released_at=a.released_at,
        release_reason=a.release_reason,
        note=a.note,
        employee_name=employee_name,
        software_name=software_name,
    )


def to_response(db: Session, a: LicenseAssignment) -> LicenseAssignmentResponse:
    """단건 응답용(부여/회수 직후). 조인 쿼리 한 번."""
    row = _joined(db).filter(LicenseAssignment.id == a.id).first()
    if row is None:
        return _to_response(a, None, None)
    assignment, employee_name, software_name = row
    return _to_response(assignment, employee_name, software_name)


@router.get("/usage", response_model=list[LicenseUsage])
def get_license_usage(db: Session = Depends(get_db)):
    """라이선스별 실시간 현황. 초과 사용을 여기서 잡는다."""
    result = []
    rows = (
        db.query(LicensePool, SoftwareProduct)
        .join(SoftwareProduct, SoftwareProduct.id == LicensePool.software_id)
        .all()
    )
    # 풀별 사용 수를 쿼리 한 번(GROUP BY)으로 전부 가져온다.
    used_by_pool = dict(
        db.query(LicenseAssignment.license_pool_id, func.count(LicenseAssignment.id))
        .filter(LicenseAssignment.released_at.is_(None))
        .group_by(LicenseAssignment.license_pool_id)
        .all()
    )
    for pool, product in rows:
        used = used_by_pool.get(pool.id, 0)
        purchased = pool.purchased_count
        available = (purchased - used) if purchased is not None else None
        result.append(
            LicenseUsage(
                license_pool_id=pool.id,
                software_id=product.id,
                software_name=product.name,
                purchased_count=purchased,
                used_count=used,
                available_count=available,
                is_over_allocated=available is not None and available < 0,
                expire_date=pool.expire_date,
            )
        )
    result.sort(key=lambda r: (not r.is_over_allocated, r.software_name))
    return result


@router.get("/", response_model=list[LicenseAssignmentResponse])
def list_license_assignments(
    employee_id: UUID | None = None,
    license_pool_id: UUID | None = None,
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    query = _joined(db)
    if employee_id:
        query = query.filter(LicenseAssignment.employee_id == employee_id)
    if license_pool_id:
        query = query.filter(LicenseAssignment.license_pool_id == license_pool_id)
    if active_only:
        query = query.filter(LicenseAssignment.released_at.is_(None))
    rows = query.order_by(LicenseAssignment.assigned_at.desc().nullslast()).all()
    return [_to_response(a, emp_name, sw_name) for a, emp_name, sw_name in rows]


@router.post("/", response_model=LicenseAssignmentResponse)
def grant_license(
    data: LicenseAssignmentCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("software")),
):
    pool = db.query(LicensePool).filter(LicensePool.id == data.license_pool_id).first()
    if not pool:
        raise HTTPException(status_code=404, detail="License pool not found")

    employee = db.query(Employee).filter(Employee.id == data.employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    if employee.status == "INACTIVE":
        raise HTTPException(
            status_code=400,
            detail="퇴사 처리된 직원에게는 라이선스를 부여할 수 없습니다",
        )

    # 같은 사람에게 같은 라이선스를 두 번 주지 않는다.
    already = db.query(LicenseAssignment).filter(
        LicenseAssignment.license_pool_id == data.license_pool_id,
        LicenseAssignment.employee_id == data.employee_id,
        LicenseAssignment.released_at.is_(None),
    ).first()
    if already:
        raise HTTPException(
            status_code=409, detail="이미 이 직원에게 부여된 라이선스입니다"
        )

    # 보유 수량을 넘어서면 막지 않고 허용하되, 현황 조회에서 초과로 표시된다.
    # (실무상 초과 상태가 이미 존재할 수 있어 등록 자체를 막으면 현실을 못 담는다)
    assignment = LicenseAssignment(
        license_pool_id=data.license_pool_id,
        employee_id=data.employee_id,
        assigned_at=data.assigned_at or date.today(),
        note=data.note,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return to_response(db, assignment)


@router.post("/{assignment_id}/release", response_model=LicenseAssignmentResponse)
def release_license(
    assignment_id: UUID,
    data: LicenseAssignmentRelease | None = None,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("software")),
):
    """개별 회수. 퇴사와 무관하게 라이선스만 뺄 때 쓴다."""
    assignment = db.query(LicenseAssignment).filter(
        LicenseAssignment.id == assignment_id
    ).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="License assignment not found")
    if assignment.released_at is not None:
        raise HTTPException(status_code=409, detail="이미 회수된 라이선스입니다")

    assignment.released_at = datetime.utcnow()
    assignment.release_reason = "MANUAL"
    if data and data.note:
        assignment.note = data.note
    db.commit()
    db.refresh(assignment)
    return to_response(db, assignment)


@router.post("/release-by-pair", response_model=LicenseAssignmentResponse)
def release_by_pair(
    employee_id: UUID,
    license_pool_id: UUID,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("software")),
):
    """부여 id 를 모를 때 '직원 + 라이선스' 조합으로 회수한다.

    화면에서 목록을 거치지 않고 바로 뺄 수 있어 편하다.
    """
    assignment = db.query(LicenseAssignment).filter(
        LicenseAssignment.employee_id == employee_id,
        LicenseAssignment.license_pool_id == license_pool_id,
        LicenseAssignment.released_at.is_(None),
    ).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="사용 중인 부여 기록이 없습니다")

    assignment.released_at = datetime.utcnow()
    assignment.release_reason = "MANUAL"
    db.commit()
    db.refresh(assignment)
    return to_response(db, assignment)
