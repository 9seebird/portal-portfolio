from datetime import date

from pydantic import BaseModel
from uuid import UUID

from app.core.enums import AssetStatus, AssetType


class AssetBase(BaseModel):
    asset_no: str | None = None
    label_no: str | None = None
    # str 이 아니라 Enum 으로 받는다. 정해진 값 외에는 422로 거른다.
    asset_type: AssetType | None = None

    manufacturer: str | None = None
    model: str | None = None
    serial_no: str | None = None

    cpu: str | None = None
    memory_gb: int | None = None
    storage_gb: int | None = None

    os: str | None = None

    purchase_type: str | None = None
    purchase_date: date | None = None

    rental_vendor: str | None = None
    rental_end_date: date | None = None

    status: AssetStatus | None = None
    qr_code: str | None = None

    notes: str | None = None


class AssetCreate(AssetBase):
    asset_no: str
    asset_type: AssetType


class AssetUpdate(AssetBase):
    pass


# 엑셀에서 넘어온 자산 중 번호가 아직 부여되지 않은 건이 있어 asset_no는 null일 수 있다.
# 응답에서는 asset_type/status 를 일부러 str 로 되돌린다.
# 새로 넣는 값은 위 Enum 으로 막지만, 이미 DB에 들어가 있는 예전 값까지
# Enum 으로 검증하면 규격 밖 값 하나 때문에 목록 조회 전체가 500으로 죽는다.
# "쓰기는 엄격하게, 읽기는 관대하게".
class AssetResponse(AssetBase):
    id: UUID
    asset_type: str | None = None
    status: str | None = None

    class Config:
        from_attributes = True


# ---- 값 정리 (제조사·모델·CPU·운영체제 표기 통일) ----

class SpecValue(BaseModel):
    """한 항목에 실제로 쓰이고 있는 값과 그 개수."""

    value: str
    count: int


class SpecValueReplace(BaseModel):
    """어떤 값을 다른 값으로 일괄 변경. to_value 가 비면 값을 지운다."""

    field: str
    from_value: str
    to_value: str | None = None
