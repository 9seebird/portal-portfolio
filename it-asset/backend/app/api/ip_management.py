from ipaddress import ip_address
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.api.permissions import require_view
from app.db.database import get_db
from app.services import ip_import
from app.models.asset import Asset
from app.models.asset_assignment import AssetAssignment
from app.models.employee import Employee
from app.models.extension import Extension
from app.models.ip_assignment import IPAssignment
from app.models.ip_range import IPRange
from app.schemas.ip import (
    IPAssignmentCreate,
    IPAssignmentResponse,
    IPAssignmentUpdate,
    IPRangeCreate,
    IPRangeResponse,
    IPRangeUpdate,
)

router = APIRouter(tags=["IP Management"], dependencies=[Depends(get_current_user)])

# IP 대역을 아직 화면에 등록하지 않았을 때 쓰는 기본값.
# ip_ranges 표에 뭔가 들어 있으면 그쪽을 쓴다 — 화면에서 고칠 수 있어야 하기 때문.
DEFAULT_IP_RANGES = [
    ("3층", "10.20.30.31", "10.20.30.219", "NETWORK"),
    ("4층", "10.20.40.31", "10.20.40.240", "NETWORK"),
]

IP_KINDS = ("NETWORK", "PHONE")


def iter_ip_range(start_ip: str, end_ip: str):
    start = int(ip_address(start_ip))
    end = int(ip_address(end_ip))
    for value in range(start, end + 1):
        yield str(ip_address(value))


@router.get("/ip-ranges", response_model=list[IPRangeResponse])
def get_ip_ranges(db: Session = Depends(get_db)):
    return db.query(IPRange).order_by(IPRange.name).all()


@router.get("/ip-addresses/free")
def get_free_ip_addresses(
    kind: str | None = None,
    db: Session = Depends(get_db),
):
    """아직 아무도 안 쓰는 IP.

    쓰는 중인 IP 는 종류를 가리지 않고 전부 뺀다. PC 와 전화기가 같은 대역을
    쓰게 되더라도 같은 주소를 두 번 내주면 안 되기 때문이다.
    """
    used_ips = {
        row.ip_address
        for row in db.query(IPAssignment).filter(
            IPAssignment.status.in_(["USED", "ACTIVE", "RESERVED"])
        ).all()
    }

    registered = db.query(IPRange).order_by(IPRange.name).all()
    if registered:
        ranges = [(r.name, r.start_ip, r.end_ip, r.kind or "NETWORK") for r in registered]
    else:
        ranges = DEFAULT_IP_RANGES

    free = []
    for name, start_ip, end_ip, range_kind in ranges:
        if kind and range_kind != kind:
            continue
        try:
            addresses = list(iter_ip_range(start_ip, end_ip))
        except ValueError:
            # 대역을 손으로 넣다가 오타가 나면 여기서 통째로 죽는다. 그 대역만 건너뛴다.
            continue
        for address in addresses:
            if address not in used_ips:
                free.append({"range": name, "kind": range_kind, "ip_address": address})
    return free


@router.post("/ip-ranges", response_model=IPRangeResponse)
def create_ip_range(
    range_data: IPRangeCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("ips")),
):
    ip_range = IPRange(**range_data.model_dump())
    db.add(ip_range)
    db.commit()
    db.refresh(ip_range)
    return ip_range


@router.put("/ip-ranges/{ip_range_id}", response_model=IPRangeResponse)
def update_ip_range(
    ip_range_id: UUID,
    range_data: IPRangeUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("ips")),
):
    ip_range = db.query(IPRange).filter(IPRange.id == ip_range_id).first()
    if not ip_range:
        raise HTTPException(status_code=404, detail="IP range not found")
    for key, value in range_data.model_dump(exclude_unset=True).items():
        setattr(ip_range, key, value)
    db.commit()
    db.refresh(ip_range)
    return ip_range


@router.delete("/ip-ranges/{ip_range_id}")
def delete_ip_range(
    ip_range_id: UUID,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("ips")),
):
    ip_range = db.query(IPRange).filter(IPRange.id == ip_range_id).first()
    if not ip_range:
        raise HTTPException(status_code=404, detail="IP range not found")

    assigned_count = db.query(func.count(IPAssignment.id)).filter(
        IPAssignment.ip_range_id == ip_range_id
    ).scalar() or 0
    if assigned_count:
        raise HTTPException(
            status_code=409,
            detail=f"이 대역에 할당된 IP가 {assigned_count}개 있습니다. 먼저 회수하세요.",
        )

    db.delete(ip_range)
    db.commit()
    return {"message": "IP range deleted"}


def _decorate(db: Session, rows: list[IPAssignment]) -> list[IPAssignmentResponse]:
    """붙은 대상의 이름을 채워서 내려준다.

    행마다 자산·내선을 다시 조회하면 N+1 이라 한 번에 모아서 붙인다.
    """
    asset_ids = {r.asset_id for r in rows if r.asset_id}
    ext_ids = {r.extension_id for r in rows if r.extension_id}

    assets = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(asset_ids))} if asset_ids else {}

    # 자산에 붙은 IP 는 '지금 그 자산을 쓰는 사람'이 곧 사용자다.
    # 자산번호만 보여주면 누구 자리를 찾아가야 할지 알 수 없다.
    holder_by_asset = {}
    if asset_ids:
        for assignment in db.query(AssetAssignment).filter(
            AssetAssignment.asset_id.in_(asset_ids),
            AssetAssignment.returned_at.is_(None),
        ).all():
            holder_by_asset[assignment.asset_id] = assignment.employee_id
    extensions = (
        {e.id: e for e in db.query(Extension).filter(Extension.id.in_(ext_ids))}
        if ext_ids else {}
    )
    employee_ids = {e.employee_id for e in extensions.values() if e.employee_id}
    employee_ids |= set(holder_by_asset.values())
    employees = (
        {e.id: e for e in db.query(Employee).filter(Employee.id.in_(employee_ids))}
        if employee_ids else {}
    )

    result = []
    for row in rows:
        extension = extensions.get(row.extension_id) if row.extension_id else None
        asset = assets.get(row.asset_id) if row.asset_id else None

        if extension and extension.employee_id:
            employee = employees.get(extension.employee_id)
        elif row.asset_id:
            employee = employees.get(holder_by_asset.get(row.asset_id))
        else:
            employee = None
        result.append(IPAssignmentResponse(
            id=row.id,
            kind=row.kind or "NETWORK",
            asset_id=row.asset_id,
            extension_id=row.extension_id,
            ip_range_id=row.ip_range_id,
            ip_address=row.ip_address,
            hostname=row.hostname,
            mac_address=row.mac_address,
            status=row.status,
            created_at=row.created_at,
            asset_no=asset.asset_no if asset else None,
            extension_number=extension.number if extension else None,
            employee_name=employee.name if employee else None,
            employee_department=employee.department if employee else None,
        ))
    return result


@router.get("/ip-assignments", response_model=list[IPAssignmentResponse])
def get_ip_assignments(
    asset_id: UUID | None = None,
    extension_id: UUID | None = None,
    kind: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(IPAssignment)
    if asset_id:
        query = query.filter(IPAssignment.asset_id == asset_id)
    if extension_id:
        query = query.filter(IPAssignment.extension_id == extension_id)
    if kind:
        query = query.filter(IPAssignment.kind == kind)
    if status:
        query = query.filter(IPAssignment.status == status)
    return _decorate(db, query.order_by(IPAssignment.ip_address).all())


def _where(db: Session, assignment: IPAssignment) -> str:
    """이 IP 가 어디에 쓰이는지 한 줄로. 중복이라고만 하면 찾아다녀야 한다."""
    if assignment.kind == "PHONE" and assignment.extension_id:
        extension = db.query(Extension).filter(Extension.id == assignment.extension_id).first()
        if extension:
            employee = (
                db.query(Employee).filter(Employee.id == extension.employee_id).first()
                if extension.employee_id else None
            )
            who = f" ({employee.name})" if employee else ""
            return f"내선 {extension.number}{who}"
    if assignment.asset_id:
        asset = db.query(Asset).filter(Asset.id == assignment.asset_id).first()
        if asset:
            return f"자산 {asset.asset_no}"
    return "다른 곳"


def _check_target(db: Session, kind: str, asset_id, extension_id, exclude_id=None) -> None:
    """종류에 맞는 대상이 제대로 왔는지 본다.

    전화기 IP 인데 자산이 붙거나, 네트워크 IP 인데 내선이 붙으면
    나중에 어느 화면에서도 안 보이는 유령 자료가 된다.
    """
    if kind not in IP_KINDS:
        raise HTTPException(status_code=400, detail=f"종류는 {IP_KINDS} 중 하나여야 합니다.")

    if kind == "NETWORK":
        if not asset_id:
            raise HTTPException(status_code=400, detail="네트워크 IP 는 자산을 지정해야 합니다.")
        if not db.query(Asset).filter(Asset.id == asset_id).first():
            raise HTTPException(status_code=404, detail="Asset not found")
        return

    # PHONE
    if not extension_id:
        raise HTTPException(status_code=400, detail="전화기 IP 는 내선번호를 지정해야 합니다.")
    extension = db.query(Extension).filter(Extension.id == extension_id).first()
    if not extension:
        raise HTTPException(status_code=404, detail="내선번호를 찾을 수 없습니다.")

    # 내선 하나에 전화기 IP 하나. 상태와 무관하게 본다 —
    # 상태로 걸러 두면 'FREE 인 전화기 IP' 가 생겨서 화면마다 보였다 안 보였다 한다.
    query = db.query(IPAssignment).filter(
        IPAssignment.extension_id == extension_id,
    )
    if exclude_id is not None:
        query = query.filter(IPAssignment.id != exclude_id)
    taken = query.first()
    if taken:
        raise HTTPException(
            status_code=409,
            detail=f"내선 {extension.number} 에는 이미 {taken.ip_address} 가 붙어 있습니다.",
        )


# /ip-assignments/import 는 {id} 를 받는 길보다 **앞에** 있어야 한다.
# 뒤에 두면 'import' 를 id 로 읽어서 422 가 난다.
@router.post("/ip-assignments/import")
async def import_ip_assignments(
    file: UploadFile = File(..., description="엑셀(.xlsx) 또는 CSV"),
    apply: bool = Form(False, description="false 면 미리보기만 한다"),
    overwrite: bool = Form(False, description="이미 쓰이고 있는 IP 도 파일 내용으로 덮어쓴다"),
    db: Session = Depends(get_db),
    _admin=Depends(require_view("ips")),
):
    """엑셀·CSV 를 올려서 IP 를 한꺼번에 넣는다.

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
        rows = ip_import.read_table(data, file.filename or "")
        planned = ip_import.plan(db, rows, overwrite=overwrite)
    except ip_import.ImportError_ as error:
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
        counts = ip_import.apply_plan(db, planned)
    except Exception:
        db.rollback()
        raise
    return {**result, "applied": True, **counts}


@router.post("/ip-assignments", response_model=IPAssignmentResponse)
def create_ip_assignment(
    assignment_data: IPAssignmentCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("ips")),
):
    _check_target(db, assignment_data.kind, assignment_data.asset_id,
                  assignment_data.extension_id)
    # 전화기 IP 에 'FREE' 는 뜻이 없다. 안 쓸 거면 지우면 된다.
    # 이걸 허용하면 IP 관리에는 보이는데 내선·직원별 현황에는 안 보이는 유령이 된다.
    if assignment_data.kind == "PHONE":
        assignment_data.status = "USED"
    if assignment_data.ip_range_id:
        ip_range = db.query(IPRange).filter(IPRange.id == assignment_data.ip_range_id).first()
        if not ip_range:
            raise HTTPException(status_code=404, detail="IP range not found")
    existing = db.query(IPAssignment).filter(
        IPAssignment.ip_address == assignment_data.ip_address
    ).first()
    if existing and existing.status != "FREE":
        raise HTTPException(
            status_code=409,
            detail=f"{assignment_data.ip_address} 는 이미 {_where(db, existing)} 에 쓰이고 있습니다.",
        )
    if existing:
        existing.kind = assignment_data.kind
        existing.asset_id = assignment_data.asset_id
        existing.extension_id = assignment_data.extension_id
        existing.ip_range_id = assignment_data.ip_range_id
        existing.hostname = assignment_data.hostname
        existing.mac_address = assignment_data.mac_address
        existing.status = assignment_data.status
        db.commit()
        db.refresh(existing)
        return _decorate(db, [existing])[0]

    assignment = IPAssignment(**assignment_data.model_dump())
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return _decorate(db, [assignment])[0]


@router.put("/ip-assignments/{assignment_id}", response_model=IPAssignmentResponse)
def update_ip_assignment(
    assignment_id: UUID,
    assignment_data: IPAssignmentUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("ips")),
):
    assignment = db.query(IPAssignment).filter(IPAssignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="IP assignment not found")
    update_data = assignment_data.model_dump(exclude_unset=True)
    new_ip = update_data.get("ip_address")
    if new_ip and new_ip != assignment.ip_address:
        existing = db.query(IPAssignment).filter(
            IPAssignment.ip_address == new_ip,
            IPAssignment.status != "FREE",
        ).first()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"{new_ip} 는 이미 {_where(db, existing)} 에 쓰이고 있습니다.",
            )

    for key, value in update_data.items():
        setattr(assignment, key, value)

    # 전화기 IP 는 내선에 붙어 있는 한 늘 '사용 중'이다 (위 create 와 같은 이유).
    if (assignment.kind or "NETWORK") == "PHONE" and assignment.extension_id:
        assignment.status = "USED"

    _check_target(db, assignment.kind or "NETWORK", assignment.asset_id,
                  assignment.extension_id, exclude_id=assignment.id)

    db.commit()
    db.refresh(assignment)
    return _decorate(db, [assignment])[0]


@router.delete("/ip-assignments/{assignment_id}")
def delete_ip_assignment(
    assignment_id: UUID,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("ips")),
):
    assignment = db.query(IPAssignment).filter(IPAssignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="IP assignment not found")
    db.delete(assignment)
    db.commit()
    return {"message": "IP assignment released"}
