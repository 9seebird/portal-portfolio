from pydantic import BaseModel


class DashboardSummary(BaseModel):
    total_assets: int
    assigned_assets: int
    storage_assets: int
    repair_assets: int
    rental_expiring: int
    license_expiring: int
    ip_usage_rate: int


class BreakdownItem(BaseModel):
    key: str
    count: int


class DashboardBreakdown(BaseModel):
    by_status: list[BreakdownItem]
    by_type: list[BreakdownItem]
