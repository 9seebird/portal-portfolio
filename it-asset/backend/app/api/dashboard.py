from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.asset import Asset
from app.models.asset_assignment import AssetAssignment
from app.models.ip_assignment import IPAssignment
from app.models.ip_range import IPRange
from app.models.license_pool import LicensePool
from app.models.rental_contract import RentalContract
from app.schemas.dashboard import BreakdownItem, DashboardBreakdown, DashboardSummary

router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"],
    dependencies=[Depends(get_current_user)],
)


def _ip_to_int(addr: str | None) -> int | None:
    parts = (addr or "").split(".")
    if len(parts) != 4:
        return None
    try:
        a, b, c, d = (int(p) for p in parts)
    except ValueError:
        return None
    return (a << 24) + (b << 16) + (c << 8) + d


@router.get("/summary", response_model=DashboardSummary)
def get_dashboard_summary(db: Session = Depends(get_db)):
    total_assets = db.query(func.count(Asset.id)).scalar() or 0
    assigned_assets = db.query(func.count(AssetAssignment.id)).filter(
        AssetAssignment.returned_at.is_(None)
    ).scalar() or 0
    storage_assets = db.query(func.count(Asset.id)).filter(Asset.status == "STORAGE").scalar() or 0
    repair_assets = db.query(func.count(Asset.id)).filter(Asset.status == "REPAIR").scalar() or 0

    rental_until = date.today() + timedelta(days=60)
    rental_expiring = db.query(func.count(RentalContract.id)).filter(
        RentalContract.status == "ACTIVE",
        RentalContract.end_date.is_not(None),
        RentalContract.end_date <= rental_until,
    ).scalar() or 0

    license_until = date.today() + timedelta(days=30)
    license_expiring = db.query(func.count(LicensePool.id)).filter(
        LicensePool.expire_date.is_not(None),
        LicensePool.expire_date <= license_until,
    ).scalar() or 0

    used_ips = db.query(func.count(IPAssignment.id)).filter(
        IPAssignment.status.in_(["USED", "ACTIVE", "RESERVED"])
    ).scalar() or 0

    # 사용률 분모는 등록된 IP 대역의 실제 주소 수 합계다(예전엔 512로 고정돼 있었다).
    total_ips = 0
    for start_ip, end_ip in db.query(IPRange.start_ip, IPRange.end_ip).all():
        start, end = _ip_to_int(start_ip), _ip_to_int(end_ip)
        if start is not None and end is not None and end >= start:
            total_ips += end - start + 1
    ip_usage_rate = min(100, int((used_ips / total_ips) * 100)) if total_ips else 0

    return DashboardSummary(
        total_assets=total_assets,
        assigned_assets=assigned_assets,
        storage_assets=storage_assets,
        repair_assets=repair_assets,
        rental_expiring=rental_expiring,
        license_expiring=license_expiring,
        ip_usage_rate=ip_usage_rate,
    )


@router.get("/breakdown", response_model=DashboardBreakdown)
def get_dashboard_breakdown(db: Session = Depends(get_db)):
    def counts(column):
        rows = db.query(column, func.count(Asset.id)).group_by(column).all()
        return [
            BreakdownItem(key=key or "UNKNOWN", count=count)
            for key, count in sorted(rows, key=lambda row: row[1], reverse=True)
        ]

    return DashboardBreakdown(
        by_status=counts(Asset.status),
        by_type=counts(Asset.asset_type),
    )
