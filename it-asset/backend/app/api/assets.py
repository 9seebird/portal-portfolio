from uuid import UUID

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.api.permissions import require_view
from app.db.database import get_db
from app.services import roster_import
from app.models.asset import Asset

from app.schemas.asset import (
    AssetCreate,
    AssetUpdate,
    AssetResponse,
    SpecValue,
    SpecValueReplace,
)

from app.models.asset_assignment import AssetAssignment
from app.models.employee import Employee
from app.models.ip_assignment import IPAssignment
from app.models.rental_contract import RentalContract
from app.models.software_installation import SoftwareInstallation

from app.schemas.asset_assignment import (
    AssetAssignCreate,
    AssetAssignmentResponse
)

router = APIRouter(
    prefix="/assets",
    tags=["Assets"],
    dependencies=[Depends(get_current_user)],
)

# 주의: 아래 값 정리 경로(/assets/spec-values)는 /assets/{asset_id} 보다
# 먼저 선언해야 한다. FastAPI 는 선언 순서대로 맞춰보기 때문에,
# 뒤에 두면 "spec-values" 가 asset_id 로 해석되어 422 가 난다.
# ---------------------------------------------------------------- 값 정리
#
# 제조사·모델·CPU·운영체제는 자산마다 문자열로 들어 있다.
# 그러다 보니 "Windows 11" 과 "Windows11" 처럼 같은 것을 다르게 적은 값이 쌓인다.
# 여기서 실제로 쓰이는 값과 개수를 보여주고, 한 값을 다른 값으로 한 번에 바꾼다.

# 문자열로 관리하는 항목만 대상. 메모리·저장장치는 숫자라 표기 흔들림이 없다.
SPEC_FIELDS = {
    "manufacturer": "제조사",
    "model": "모델",
    "cpu": "CPU",
    "os": "운영체제",
}


def _spec_column(field: str):
    if field not in SPEC_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"정리할 수 있는 항목은 {list(SPEC_FIELDS)} 입니다.",
        )
    return getattr(Asset, field)


# /import 는 {id} 를 받는 길보다 **앞에** 있어야 한다.
# 뒤에 두면 'import' 를 id 로 읽어서 422 가 난다.
@router.post("/import")
async def import_assets(
    file: UploadFile = File(..., description="엑셀(.xlsx) 또는 CSV"),
    apply: bool = Form(False, description="false 면 미리보기만 한다"),
    overwrite: bool = Form(False, description="이미 있는 것도 파일 내용으로 덮어쓴다"),
    db: Session = Depends(get_db),
    _admin=Depends(require_view("assets")),
):
    """엑셀·CSV 를 올려서 한꺼번에 넣는다.

    기본은 미리보기다. 무엇이 들어가고 무엇이 왜 빠지는지 먼저 보여주고,
    apply=true 로 한 번 더 불러야 실제로 들어간다 — 남의 자료를 한 방에
    갈아엎는 일은 없어야 하기 때문이다.

    칸 이름은 화면의 「CSV 내려받기」가 내보내는 것과 같다. 목록을 받아
    줄만 채워 그대로 올릴 수 있다.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="파일이 너무 큽니다 (5MB 까지).")

    try:
        rows = roster_import.read_table(data, file.filename or "")
        planned = roster_import.plan_assets(db, rows, overwrite=overwrite)
    except roster_import.ImportError_ as error:
        raise HTTPException(status_code=400, detail=str(error))

    result = {"applied": False, "columns": planned["columns"],
               "new": planned["new"], "update": planned["update"],
               "skipped": planned["skipped"]}
    if not apply:
        return result

    try:
        counts = roster_import.apply_assets(db, planned)
    except Exception:
        db.rollback()
        raise
    return {**result, "applied": True, **counts}


@router.get("/spec-values", response_model=list[SpecValue])
def list_spec_values(field: str, db: Session = Depends(get_db)):
    """한 항목에 실제로 쓰이는 값과 사용 대수. 많이 쓰는 값이 위로."""
    column = _spec_column(field)
    rows = (
        db.query(column, func.count(Asset.id))
        .filter(column.isnot(None), column != "")
        .group_by(column)
        .order_by(func.count(Asset.id).desc(), column)
        .all()
    )
    return [SpecValue(value=value, count=count) for value, count in rows]


@router.post("/spec-values/replace")
def replace_spec_value(
    payload: SpecValueReplace,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("assets")),
):
    """어떤 값을 쓰는 자산을 모두 다른 값으로 바꾼다. to_value 가 비면 값을 지운다."""
    column = _spec_column(payload.field)

    source = (payload.from_value or "").strip()
    if not source:
        raise HTTPException(status_code=400, detail="바꿀 원본 값이 비어 있습니다.")

    target = (payload.to_value or "").strip() or None
    if target == source:
        raise HTTPException(status_code=400, detail="원본과 바꿀 값이 같습니다.")

    changed = (
        db.query(Asset)
        .filter(column == source)
        .update({payload.field: target}, synchronize_session=False)
    )
    db.commit()
    return {"changed": changed, "from": source, "to": target}

# 목록 조회

@router.get("/", response_model=list[AssetResponse])
def get_assets(
    asset_type: str | None = None,
    status: str | None = None,
    employee_id: UUID | None = None,
    db: Session = Depends(get_db)
):
    query = db.query(Asset)
    if asset_type:
        query = query.filter(Asset.asset_type == asset_type)
    if status:
        query = query.filter(Asset.status == status)
    if employee_id:
        query = (
            query.join(AssetAssignment)
            .filter(AssetAssignment.employee_id == employee_id)
            .filter(AssetAssignment.returned_at.is_(None))
        )
    return query.order_by(Asset.asset_no).all()


# 단건 조회

@router.get("/{asset_id}", response_model=AssetResponse)
def get_asset(
    asset_id: UUID,
    db: Session = Depends(get_db)
):
    asset = db.query(Asset).filter(
        Asset.id == asset_id
    ).first()

    if not asset:
        raise HTTPException(
            status_code=404,
            detail="Asset not found"
        )

    return asset

# 등록

@router.post("/", response_model=AssetResponse)
def create_asset(
    asset_data: AssetCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("assets")),
):
    data = asset_data.model_dump()
    # 상태를 안 주면 '보관'. model_dump() 가 status=None 을 그대로 실어 보내기 때문에
    # 컬럼 기본값만 믿으면 NULL 이 들어간다.
    if not data.get("status"):
        data["status"] = "STORAGE"

    asset = Asset(**data)

    db.add(asset)
    db.commit()
    db.refresh(asset)

    return asset

# 수정

@router.put("/{asset_id}", response_model=AssetResponse)
def update_asset(
    asset_id: UUID,
    asset_data: AssetUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("assets")),
):
    asset = db.query(Asset).filter(
        Asset.id == asset_id
    ).first()

    if not asset:
        raise HTTPException(
            status_code=404,
            detail="Asset not found"
        )

    update_data = asset_data.model_dump(
        exclude_unset=True
    )

    new_asset_no = update_data.get("asset_no")
    if new_asset_no and new_asset_no != asset.asset_no:
        existing = db.query(Asset).filter(Asset.asset_no == new_asset_no).first()
        if existing:
            raise HTTPException(
                status_code=409,
                detail="Asset number already exists"
            )

    for key, value in update_data.items():
        setattr(asset, key, value)

    db.commit()
    db.refresh(asset)

    return asset

# 삭제

@router.delete("/{asset_id}")
def delete_asset(
    asset_id: UUID,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("assets")),
):
    asset = db.query(Asset).filter(
        Asset.id == asset_id
    ).first()

    if not asset:
        raise HTTPException(
            status_code=404,
            detail="Asset not found"
        )

    db.query(IPAssignment).filter(
        IPAssignment.asset_id == asset_id
    ).delete(synchronize_session=False)
    db.query(SoftwareInstallation).filter(
        SoftwareInstallation.asset_id == asset_id
    ).delete(synchronize_session=False)
    db.query(RentalContract).filter(
        RentalContract.asset_id == asset_id
    ).delete(synchronize_session=False)
    db.query(AssetAssignment).filter(
        AssetAssignment.asset_id == asset_id
    ).delete(synchronize_session=False)
    db.delete(asset)
    db.commit()

    return {
        "message": "Asset deleted"
    }

@router.post(
    "/{asset_id}/assign",
    response_model=AssetAssignmentResponse
)
def assign_asset(
    asset_id: UUID,
    assign_data: AssetAssignCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("assets")),
):
    asset = db.query(Asset).filter(
        Asset.id == asset_id
    ).first()

    if not asset:
        raise HTTPException(
            status_code=404,
            detail="Asset not found"
        )

    employee = db.query(Employee).filter(
        Employee.id == assign_data.employee_id
    ).first()

    if not employee:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    assignment = AssetAssignment(
        asset_id=asset_id,
        employee_id=assign_data.employee_id
    )

    (
        db.query(AssetAssignment)
        .filter(AssetAssignment.asset_id == asset_id)
        .filter(AssetAssignment.returned_at.is_(None))
        .update({"returned_at": datetime.utcnow()})
    )
    asset.status = "IN_USE"

    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    return assignment


@router.post(
    "/{asset_id}/return",
    response_model=AssetAssignmentResponse
)
def return_asset(
    asset_id: UUID,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("assets")),
):
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    assignment = (
        db.query(AssetAssignment)
        .filter(AssetAssignment.asset_id == asset_id)
        .filter(AssetAssignment.returned_at.is_(None))
        .first()
    )
    if not assignment:
        raise HTTPException(status_code=404, detail="Active assignment not found")

    assignment.returned_at = datetime.utcnow()
    asset.status = "STORAGE"
    db.query(IPAssignment).filter(
        IPAssignment.asset_id == asset_id,
        IPAssignment.status.in_(["USED", "ACTIVE", "RESERVED"]),
    ).update({"status": "FREE"})
    db.commit()
    db.refresh(assignment)
    return assignment

@router.get(
    "/{asset_id}/history",
    response_model=list[AssetAssignmentResponse]
)
def get_asset_history(
    asset_id: UUID,
    db: Session = Depends(get_db)
):
    return (
        db.query(AssetAssignment)
        .filter(
            AssetAssignment.asset_id == asset_id
        )
        .all()
    )
