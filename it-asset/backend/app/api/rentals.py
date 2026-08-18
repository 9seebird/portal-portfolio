from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.api.permissions import require_view
from app.db.database import get_db
from app.models.asset import Asset
from app.models.rental_contract import RentalContract
from app.schemas.rental import RentalContractCreate, RentalContractResponse, RentalContractUpdate

router = APIRouter(
    prefix="/rental-contracts",
    tags=["Rental Contracts"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/", response_model=list[RentalContractResponse])
def get_rental_contracts(
    asset_id: UUID | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(RentalContract)
    if asset_id:
        query = query.filter(RentalContract.asset_id == asset_id)
    if status:
        query = query.filter(RentalContract.status == status)
    return query.order_by(RentalContract.end_date.nullslast()).all()


@router.post("/", response_model=RentalContractResponse)
def create_rental_contract(
    contract_data: RentalContractCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("rentals")),
):
    asset = db.query(Asset).filter(Asset.id == contract_data.asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    contract = RentalContract(**contract_data.model_dump())
    db.add(contract)
    db.commit()
    db.refresh(contract)
    return contract


@router.get("/expiring", response_model=list[RentalContractResponse])
def get_expiring_rental_contracts(days: int = 60, db: Session = Depends(get_db)):
    until = date.today() + timedelta(days=days)
    return db.query(RentalContract).filter(
        RentalContract.status == "ACTIVE",
        RentalContract.end_date.is_not(None),
        RentalContract.end_date <= until,
    ).order_by(RentalContract.end_date).all()


@router.put("/{contract_id}", response_model=RentalContractResponse)
def update_rental_contract(
    contract_id: UUID,
    contract_data: RentalContractUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("rentals")),
):
    contract = db.query(RentalContract).filter(RentalContract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Rental contract not found")
    for key, value in contract_data.model_dump(exclude_unset=True).items():
        setattr(contract, key, value)
    db.commit()
    db.refresh(contract)
    return contract


@router.delete("/{contract_id}")
def delete_rental_contract(
    contract_id: UUID,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("rentals")),
):
    contract = db.query(RentalContract).filter(RentalContract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Rental contract not found")
    db.delete(contract)
    db.commit()
    return {"message": "Rental contract deleted"}
