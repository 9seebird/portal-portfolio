from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.api.permissions import require_view
from app.db.database import get_db
from app.models.asset import Asset
from app.models.license_assignment import LicenseAssignment
from app.models.license_pool import LicensePool
from app.models.software_installation import SoftwareInstallation
from app.models.software_product import SoftwareProduct
from app.schemas.software import (
    LicensePoolCreate,
    LicensePoolResponse,
    LicensePoolUpdate,
    SoftwareInstallationCreate,
    SoftwareInstallationResponse,
    SoftwareProductCreate,
    SoftwareProductResponse,
    SoftwareProductUpdate,
)

router = APIRouter(tags=["Software"], dependencies=[Depends(get_current_user)])


@router.get("/software-products", response_model=list[SoftwareProductResponse])
def get_software_products(db: Session = Depends(get_db)):
    return db.query(SoftwareProduct).order_by(SoftwareProduct.name).all()


@router.post("/software-products", response_model=SoftwareProductResponse)
def create_software_product(
    product_data: SoftwareProductCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("software")),
):
    product = SoftwareProduct(**product_data.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.put("/software-products/{product_id}", response_model=SoftwareProductResponse)
def update_software_product(
    product_id: UUID,
    product_data: SoftwareProductUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("software")),
):
    product = db.query(SoftwareProduct).filter(SoftwareProduct.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Software product not found")
    for key, value in product_data.model_dump(exclude_unset=True).items():
        setattr(product, key, value)
    db.commit()
    db.refresh(product)
    return product


@router.delete("/software-products/{product_id}")
def delete_software_product(
    product_id: UUID,
    db: Session = Depends(get_db),
    force: bool = False,
    _admin=Depends(require_view("software")),
):
    """소프트웨어 삭제.

    라이선스 부여 이력(license_assignments)이 라이선스 보유(license_pools)를
    참조하므로, 이력을 남겨둔 채 보유를 지우면 외래키 위반으로 500 이 난다.
    부여 이력이 있으면 몇 건인지 알려주고 막는다. force=true 면 이력까지 지운다.
    """
    product = db.query(SoftwareProduct).filter(SoftwareProduct.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Software product not found")

    installed_count = db.query(func.count(SoftwareInstallation.id)).filter(
        SoftwareInstallation.software_id == product_id
    ).scalar() or 0
    if installed_count:
        raise HTTPException(
            status_code=409,
            detail=f"설치된 자산이 {installed_count}대 있습니다. 설치 내역을 먼저 제거하세요.",
        )

    pool_ids = [
        row[0] for row in
        db.query(LicensePool.id).filter(LicensePool.software_id == product_id).all()
    ]

    if pool_ids:
        assignment_query = db.query(LicenseAssignment).filter(
            LicenseAssignment.license_pool_id.in_(pool_ids)
        )
        held = assignment_query.filter(LicenseAssignment.released_at.is_(None)).count()
        total = assignment_query.count()

        if total and not force:
            detail = (
                f"'{product.name}' 에 라이선스 부여 이력 {total}건이 있습니다"
                + (f" (지금 보유 중 {held}명)" if held else "")
                + ". 이력까지 지우려면 force=true 로 요청하세요."
            )
            raise HTTPException(status_code=409, detail=detail)

        if force:
            assignment_query.delete(synchronize_session=False)

    db.query(LicensePool).filter(
        LicensePool.software_id == product_id
    ).delete(synchronize_session=False)
    db.delete(product)
    db.commit()
    return {"message": "Software product deleted"}


@router.get("/license-pools", response_model=list[LicensePoolResponse])
def get_license_pools(db: Session = Depends(get_db)):
    return db.query(LicensePool).order_by(LicensePool.expire_date.nullslast()).all()


@router.post("/license-pools", response_model=LicensePoolResponse)
def create_license_pool(
    pool_data: LicensePoolCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("software")),
):
    product = db.query(SoftwareProduct).filter(SoftwareProduct.id == pool_data.software_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Software product not found")
    pool = LicensePool(**pool_data.model_dump())
    db.add(pool)
    db.commit()
    db.refresh(pool)
    return pool


@router.get("/license-pools/expiring", response_model=list[LicensePoolResponse])
def get_expiring_license_pools(days: int = 30, db: Session = Depends(get_db)):
    until = date.today() + timedelta(days=days)
    return db.query(LicensePool).filter(
        LicensePool.expire_date.is_not(None),
        LicensePool.expire_date <= until,
    ).order_by(LicensePool.expire_date).all()


@router.put("/license-pools/{pool_id}", response_model=LicensePoolResponse)
def update_license_pool(
    pool_id: UUID,
    pool_data: LicensePoolUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("software")),
):
    pool = db.query(LicensePool).filter(LicensePool.id == pool_id).first()
    if not pool:
        raise HTTPException(status_code=404, detail="License pool not found")
    for key, value in pool_data.model_dump(exclude_unset=True).items():
        setattr(pool, key, value)
    db.commit()
    db.refresh(pool)
    return pool


@router.delete("/license-pools/{pool_id}")
def delete_license_pool(
    pool_id: UUID,
    db: Session = Depends(get_db),
    force: bool = False,
    _admin=Depends(require_view("software")),
):
    """라이선스 보유 삭제. 부여 이력이 매달려 있으면 같은 이유로 막는다."""
    pool = db.query(LicensePool).filter(LicensePool.id == pool_id).first()
    if not pool:
        raise HTTPException(status_code=404, detail="License pool not found")

    assignment_query = db.query(LicenseAssignment).filter(
        LicenseAssignment.license_pool_id == pool_id
    )
    total = assignment_query.count()
    if total and not force:
        held = assignment_query.filter(LicenseAssignment.released_at.is_(None)).count()
        raise HTTPException(
            status_code=409,
            detail=f"라이선스 부여 이력 {total}건이 있습니다"
                   + (f" (지금 보유 중 {held}명)" if held else "")
                   + ". 이력까지 지우려면 force=true 로 요청하세요.",
        )
    if force:
        assignment_query.delete(synchronize_session=False)

    db.delete(pool)
    db.commit()
    return {"message": "License pool deleted"}


@router.get("/software-installations", response_model=list[SoftwareInstallationResponse])
def get_software_installations(
    asset_id: UUID | None = None,
    software_id: UUID | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(SoftwareInstallation)
    if asset_id:
        query = query.filter(SoftwareInstallation.asset_id == asset_id)
    if software_id:
        query = query.filter(SoftwareInstallation.software_id == software_id)
    return query.order_by(SoftwareInstallation.installed_at.desc()).all()


@router.post("/software-installations", response_model=SoftwareInstallationResponse)
def create_software_installation(
    installation_data: SoftwareInstallationCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("software")),
):
    product = db.query(SoftwareProduct).filter(
        SoftwareProduct.id == installation_data.software_id
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Software product not found")
    asset = db.query(Asset).filter(Asset.id == installation_data.asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    installation = SoftwareInstallation(**installation_data.model_dump())
    db.add(installation)
    db.commit()
    db.refresh(installation)
    return installation


@router.delete("/software-installations/{installation_id}")
def delete_software_installation(
    installation_id: UUID,
    db: Session = Depends(get_db),
    _admin=Depends(require_view("software")),
):
    installation = db.query(SoftwareInstallation).filter(
        SoftwareInstallation.id == installation_id
    ).first()
    if not installation:
        raise HTTPException(status_code=404, detail="Software installation not found")
    db.delete(installation)
    db.commit()
    return {"message": "Software installation removed"}
