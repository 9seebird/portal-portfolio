from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.api.permissions import require_view
from app.db.database import get_db
from app.services import roster_import
from app.models.asset import Asset
from app.models.asset_assignment import AssetAssignment
from app.models.employee import Employee
from app.models.extension import Extension
from app.models.ip_assignment import IPAssignment
from app.models.license_assignment import LicenseAssignment
from app.models.software_installation import SoftwareInstallation
from app.models.software_product import SoftwareProduct
from app.schemas.employee import (
    EmployeeCreate,
    EmployeeUpdate,
    EmployeeResponse
)

from uuid import UUID
from fastapi import HTTPException

router = APIRouter(
    prefix="/employees",
    tags=["Employees"],
    dependencies=[Depends(get_current_user)],
)


# /import 는 {id} 를 받는 길보다 **앞에** 있어야 한다.
# 뒤에 두면 'import' 를 id 로 읽어서 422 가 난다.
@router.post("/import")
async def import_employees(
    file: UploadFile = File(..., description="엑셀(.xlsx) 또는 CSV"),
    apply: bool = Form(False, description="false 면 미리보기만 한다"),
    overwrite: bool = Form(False, description="이미 있는 것도 파일 내용으로 덮어쓴다"),
    db: Session = Depends(get_db),
    _admin=Depends(require_view("employees")),
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
        planned = roster_import.plan_employees(db, rows, overwrite=overwrite)
    except roster_import.ImportError_ as error:
        raise HTTPException(status_code=400, detail=str(error))

    result = {"applied": False, "columns": planned["columns"],
               "new": planned["new"], "update": planned["update"],
               "skipped": planned["skipped"]}
    if not apply:
        return result

    try:
        counts = roster_import.apply_employees(db, planned)
    except Exception:
        db.rollback()
        raise
    return {**result, "applied": True, **counts}


@router.get("/", response_model=list[EmployeeResponse])
def get_employees(
    name: str | None = None,
    department: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db)
):
    query = db.query(Employee)
    if name:
        query = query.filter(Employee.name.ilike(f"%{name}%"))
    if department:
        query = query.filter(Employee.department == department)
    if status:
        query = query.filter(Employee.status == status)
    return query.order_by(Employee.name).all()


@router.post("/", response_model=EmployeeResponse)
def create_employee(
    employee: EmployeeCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("employees")),
):
    db_employee = Employee(**employee.model_dump())

    db.add(db_employee)
    db.commit()
    db.refresh(db_employee)

    return db_employee


@router.get("/workspace")
def get_employee_workspace(db: Session = Depends(get_db)):
    employees = db.query(Employee).order_by(Employee.name).all()
    active_assignments = (
        db.query(AssetAssignment, Asset)
        .join(Asset, Asset.id == AssetAssignment.asset_id)
        .filter(AssetAssignment.returned_at.is_(None))
        .all()
    )

    asset_ids = [asset.id for _, asset in active_assignments]
    ip_by_asset = {}
    software_by_asset = {}
    if asset_ids:
        for ip in db.query(IPAssignment).filter(
            IPAssignment.asset_id.in_(asset_ids),
            IPAssignment.status.in_(["USED", "ACTIVE", "RESERVED"]),
        ).all():
            ip_by_asset.setdefault(ip.asset_id, []).append(
                {
                    "id": str(ip.id),
                    "ip_address": ip.ip_address,
                    "hostname": ip.hostname,
                    "mac_address": ip.mac_address,
                    "status": ip.status,
                }
            )

        installations = (
            db.query(SoftwareInstallation, SoftwareProduct)
            .join(SoftwareProduct, SoftwareProduct.id == SoftwareInstallation.software_id)
            .filter(SoftwareInstallation.asset_id.in_(asset_ids))
            .all()
        )
        for installation, product in installations:
            software_by_asset.setdefault(installation.asset_id, []).append(
                {
                    "id": str(installation.id),
                    "name": product.name,
                    "vendor": product.vendor,
                    "license_type": product.license_type,
                    "installed_at": installation.installed_at.isoformat()
                    if installation.installed_at
                    else None,
                }
            )

    # 내선번호는 사람에게 붙는다. 한 번에 모아둬야 직원마다 다시 묻지 않는다(N+1).
    ext_rows = db.query(Extension).filter(Extension.employee_id.isnot(None)).all()
    extension_by_employee = {row.employee_id: row.number for row in ext_rows}

    # 전화기 IP 도 같이. 내선 -> IP 를 먼저 만들고 직원에 붙인다.
    phone_ip_by_extension = {
        row.extension_id: row.ip_address
        # 상태로 거르지 않는다 (extensions.py 의 _phone_ips 와 같은 이유).
        for row in db.query(IPAssignment).filter(
            IPAssignment.kind == "PHONE",
            IPAssignment.extension_id.isnot(None),
        ).all()
    }
    phone_ip_by_employee = {
        row.employee_id: phone_ip_by_extension[row.id]
        for row in ext_rows if row.id in phone_ip_by_extension
    }

    assets_by_employee = {}
    for assignment, asset in active_assignments:
        assets_by_employee.setdefault(assignment.employee_id, []).append(
            {
                "assignment_id": str(assignment.id),
                "id": str(asset.id),
                "asset_no": asset.asset_no,
                "label_no": asset.label_no,
                "asset_type": asset.asset_type,
                "purchase_type": asset.purchase_type,
                "manufacturer": asset.manufacturer,
                "model": asset.model,
                "serial_no": asset.serial_no,
                "cpu": asset.cpu,
                "memory_gb": asset.memory_gb,
                "os": asset.os,
                "status": asset.status,
                "ips": ip_by_asset.get(asset.id, []),
                "software": software_by_asset.get(asset.id, []),
            }
        )

    return [
        {
            "id": str(employee.id),
            "emp_no": employee.emp_no,
            "name": employee.name,
            "department": employee.department,
            "position": employee.position,
            "rank": employee.rank,
            "email": employee.email,
            "phone": employee.phone,
            "extension": extension_by_employee.get(employee.id),
            "phone_ip": phone_ip_by_employee.get(employee.id),
            "status": employee.status,
            "assets": assets_by_employee.get(employee.id, []),
        }
        for employee in employees
    ]

@router.get("/{employee_id}", response_model=EmployeeResponse)
def get_employee(
    employee_id: UUID,
    db: Session = Depends(get_db)
):
    employee = db.query(Employee).filter(
        Employee.id == employee_id
    ).first()

    if not employee:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    return employee


@router.post("/{employee_id}/offboard")
def offboard_employee(
    employee_id: UUID,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("employees")),
):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    now = datetime.utcnow()
    assignments = db.query(AssetAssignment).filter(
        AssetAssignment.employee_id == employee_id,
        AssetAssignment.returned_at.is_(None),
    ).all()

    returned_assets = 0
    released_ips = 0
    for assignment in assignments:
        assignment.returned_at = now
        asset = db.query(Asset).filter(Asset.id == assignment.asset_id).first()
        if asset:
            asset.status = "STORAGE"
            returned_assets += 1
        ips = db.query(IPAssignment).filter(
            IPAssignment.asset_id == assignment.asset_id,
            IPAssignment.status.in_(["USED", "ACTIVE", "RESERVED"]),
        ).all()
        for ip in ips:
            ip.status = "FREE"
            released_ips += 1

    # 라이선스도 함께 회수한다.
    # 이걸 안 하면 퇴사자가 계속 자리를 차지해 사용 수량이 실제보다 부풀어 오른다.
    released_licenses = db.query(LicenseAssignment).filter(
        LicenseAssignment.employee_id == employee_id,
        LicenseAssignment.released_at.is_(None),
    ).update(
        {"released_at": now, "release_reason": "OFFBOARD"},
        synchronize_session=False,
    )

    # 내선번호도 반납한다. 안 그러면 없는 사람이 번호를 계속 물고 있어서
    # 새로 들어온 사람에게 그 번호를 줄 수 없다.
    released_extensions = db.query(Extension).filter(
        Extension.employee_id == employee_id,
    ).update({"employee_id": None}, synchronize_session=False)

    employee.status = "INACTIVE"
    employee.resign_date = employee.resign_date or now.date()
    db.commit()

    return {
        "message": "Employee offboarded",
        "returned_assets": returned_assets,
        "released_ips": released_ips,
        "released_licenses": released_licenses,
        "released_extensions": released_extensions,
    }

@router.put("/{employee_id}", response_model=EmployeeResponse)
def update_employee(
    employee_id: UUID,
    employee_data: EmployeeUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("employees")),
):
    employee = db.query(Employee).filter(
        Employee.id == employee_id
    ).first()

    if not employee:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    update_data = employee_data.model_dump(
        exclude_unset=True
    )

    for key, value in update_data.items():
        setattr(employee, key, value)

    db.commit()
    db.refresh(employee)

    return employee

@router.delete("/{employee_id}")
def delete_employee(
    employee_id: UUID,
    db: Session = Depends(get_db),
    force: bool = False,
    _admin=Depends(require_view("employees")),
):
    employee = db.query(Employee).filter(
        Employee.id == employee_id
    ).first()

    if not employee:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    active_assignments = db.query(AssetAssignment).filter(
        AssetAssignment.employee_id == employee_id,
        AssetAssignment.returned_at.is_(None),
    ).all()
    if active_assignments and not force:
        raise HTTPException(
            status_code=409,
            detail="Employee has assigned assets. Offboard first or use force=true.",
        )

    if force:
        now = datetime.utcnow()
        for assignment in active_assignments:
            assignment.returned_at = now
            asset = db.query(Asset).filter(Asset.id == assignment.asset_id).first()
            if asset:
                asset.status = "STORAGE"
            for ip in db.query(IPAssignment).filter(
                IPAssignment.asset_id == assignment.asset_id,
                IPAssignment.status.in_(["USED", "ACTIVE", "RESERVED"]),
            ).all():
                ip.status = "FREE"

    # 삭제는 '잘못 넣은 데이터 정리용'이다. 퇴사자는 offboard 로 INACTIVE 처리해
    # 이력을 남기는 것이 원칙이다 — 감사 대응("계정 권한 이력")이 이 기록을 요구한다.
    # 이력(반납된 지급, 회수된 라이선스)이 있는 직원은 force 없이 지울 수 없게 막는다.
    history_count = (
        db.query(AssetAssignment)
        .filter(AssetAssignment.employee_id == employee_id)
        .count()
        + db.query(LicenseAssignment)
        .filter(LicenseAssignment.employee_id == employee_id)
        .count()
    )
    if history_count and not force:
        raise HTTPException(
            status_code=409,
            detail=(
                f"이 직원에게 지급/라이선스 이력 {history_count}건이 있습니다. "
                "퇴사자는 삭제 대신 offboard 로 남겨두세요. "
                "잘못 등록한 데이터가 확실하면 force=true 로 삭제할 수 있습니다."
            ),
        )

    db.query(AssetAssignment).filter(
        AssetAssignment.employee_id == employee_id
    ).delete(synchronize_session=False)
    # license_assignments 를 지우지 않으면 Postgres 에서 FK 오류로 500이 난다.
    db.query(LicenseAssignment).filter(
        LicenseAssignment.employee_id == employee_id
    ).delete(synchronize_session=False)
    db.delete(employee)
    db.commit()

    return {
        "message": "Employee deleted"
    }
