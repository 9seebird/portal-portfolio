from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.api.permissions import require_view
from app.db.database import get_db
from app.models.asset import Asset
from app.models.asset_assignment import AssetAssignment
from app.models.employee import Employee
from app.models.ip_assignment import IPAssignment
from app.schemas.asset_assignment import AssetAssignmentCreate, AssetAssignmentResponse

router = APIRouter(
    prefix="/asset-assignments",
    tags=["Asset Assignments"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/", response_model=list[AssetAssignmentResponse])
def get_asset_assignments(
    asset_id: UUID | None = None,
    employee_id: UUID | None = None,
    active_only: bool = False,
    db: Session = Depends(get_db)
):
    query = db.query(AssetAssignment)
    if asset_id:
        query = query.filter(AssetAssignment.asset_id == asset_id)
    if employee_id:
        query = query.filter(AssetAssignment.employee_id == employee_id)
    if active_only:
        query = query.filter(AssetAssignment.returned_at.is_(None))
    return query.order_by(AssetAssignment.assigned_at.desc()).all()


@router.post("/", response_model=AssetAssignmentResponse)
def create_asset_assignment(
    assignment_data: AssetAssignmentCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("assets")),
):
    asset = db.query(Asset).filter(Asset.id == assignment_data.asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    employee = db.query(Employee).filter(Employee.id == assignment_data.employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    db.query(AssetAssignment).filter(
        AssetAssignment.asset_id == assignment_data.asset_id,
        AssetAssignment.returned_at.is_(None),
    ).update({"returned_at": datetime.utcnow()})

    assignment = AssetAssignment(
        asset_id=assignment_data.asset_id,
        employee_id=assignment_data.employee_id,
    )
    asset.status = "IN_USE"
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment


@router.post("/return", response_model=AssetAssignmentResponse)
def return_asset_assignment(
    asset_id: UUID,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("assets")),
):
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    assignment = db.query(AssetAssignment).filter(
        AssetAssignment.asset_id == asset_id,
        AssetAssignment.returned_at.is_(None),
    ).first()
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
