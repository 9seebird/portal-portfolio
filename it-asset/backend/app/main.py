import os
import json
import threading
import urllib.request
import urllib.error

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.asset_assignments import router as asset_assignment_router
from app.api.employees import router as employee_router
from app.api.assets import router as asset_router
from app.api.dashboard import router as dashboard_router
from app.api.extensions import router as extension_router
from app.api.ip_management import router as ip_management_router
from app.api.rentals import router as rental_router
from app.api.software import router as software_router
from app.api.license_assignments import router as license_assignment_router
from app.api.permissions import router as permission_router
from app.api.seats import router as seat_router
from app.core.settings import settings

app = FastAPI(
    title="IT Asset Portal",
    version="0.1.0"
)

# allow_origins=["*"] 와 allow_credentials=True 는 같이 쓰면 안 된다.
# 브라우저 표준상 그 조합은 거부되고, 무엇보다 아무 사이트나
# 로그인된 사용자 권한으로 이 API를 부를 수 있게 된다.
# 허용 출처는 .env 의 CORS_ORIGINS 에 명시한다.
#
# ※ 사내 포털 아래로 들어오면 화면과 API 가 같은 주소에서 나가므로
#   브라우저 입장에서는 CORS 자체가 없다. 이 설정은 개발용으로만 남는다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz", tags=["Health"])
def healthz():
    """컨테이너 헬스체크용. 인증 없이 접근 가능해야 한다."""
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────
# 사내 포털에 자기를 등록한다 (표준 규칙 22)
#
# 앱이 뜰 때마다 포털에 "나 여기 있다"고 알린다. 그래야 IT 담당자가
# 관리자 화면에서 손으로 서비스를 만들지 않아도 되고, 이름·설명·검색어를
# 고쳤을 때 그것이 포털에 저절로 반영된다.
#
# 처음 등록되면 **중지 상태**로 들어간다. 접근 범위와 담당자를 정하고
# 켜는 것은 사람이 한다. 앱이 스스로 켜지면 아무나 볼 수 있게 된다.
#
# keywords 는 챗에서 이 앱을 찾는 근거가 된다. 직원이 실제로 쓰는 말을 넣는다.
# 실패해도 앱은 정상 동작해야 한다 (포털이 아직 안 떠 있을 수 있다).
# ─────────────────────────────────────────────────────────────
PORTAL_API_URL = os.environ.get("PORTAL_API_URL", "").rstrip("/")
AUDIT_TOKEN = os.environ.get("AUDIT_TOKEN", "")

SERVICE_META = {
    "id": "it-asset",
    "name": "IT 자산 관리",
    "description": "사내 IT 자산·직원·IP·내선·소프트웨어·라이선스·자리 배치를 관리합니다.",
    "keywords": (
        "자산, 자산관리, 자산 대장, 노트북, 데스크톱, 모니터, 재고, 장비, "
        "직원 명단, 사번, IP, 아이피, 내선, 전화번호, 자리, 좌석, 자리배치, "
        "소프트웨어, 라이선스, 라이센스, 렌탈, 갱신, 만료"
    ),
    "url": "/it-asset/",
}


def _register_with_portal() -> None:
    if not PORTAL_API_URL or not AUDIT_TOKEN:
        print("[포털 등록] PORTAL_API_URL 또는 AUDIT_TOKEN 이 없어 건너뜁니다.")
        return
    body = json.dumps(SERVICE_META, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{PORTAL_API_URL}/api/services/register",
        data=body,
        headers={"Content-Type": "application/json",
                 "X-Service-Token": AUDIT_TOKEN},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            print("[포털 등록]", r.status, r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 403 이면 AUDIT_TOKEN 이 포털과 다른 것이다. 가장 흔한 실수라 따로 알린다.
        print(f"[포털 등록 실패] HTTP {e.code} — "
              f"{'AUDIT_TOKEN 이 포털과 같은 값인지 확인하세요.' if e.code == 403 else e.reason}")
    except Exception as e:  # noqa: BLE001
        print(f"[포털 등록 실패] {type(e).__name__}: {e} (앱은 계속 동작합니다)")


@app.on_event("startup")
def _startup() -> None:
    # 포털이 응답하지 않아도 이 앱의 기동이 늦어지지 않도록 별도 스레드에서 부른다.
    threading.Thread(target=_register_with_portal, daemon=True).start()


app.include_router(employee_router)
app.include_router(auth_router)
app.include_router(asset_router)
app.include_router(asset_assignment_router)
app.include_router(ip_management_router)
app.include_router(rental_router)
app.include_router(software_router)
app.include_router(license_assignment_router)
app.include_router(seat_router)
app.include_router(extension_router)
app.include_router(dashboard_router)
app.include_router(permission_router)


@app.on_event("startup")
def ensure_permission_table():
    """권한 표가 없으면 만든다.

    이 앱은 마이그레이션(alembic upgrade head)을 **사람이 손으로** 돌린다.
    배포할 때 그 한 줄을 빠뜨리면 첫 화면부터 500 이 나는데, 원인이
    "표가 없다" 라는 걸 알아채기까지 한참 걸린다.

    다른 표는 건드리지 않는다. 여기서 만드는 것은 이번에 새로 생긴
    app_users 하나뿐이고, 이미 있으면 아무 일도 하지 않는다.
    """
    try:
        from app.db.database import engine
        from app.models.app_user import AppUser
        AppUser.__table__.create(bind=engine, checkfirst=True)
    except Exception as error:  # noqa: BLE001
        print(f"[경고] app_users 표를 확인하지 못했습니다: {error}", flush=True)


@app.get("/")
def root():
    return {"message": "IT Asset Portal API"}
