"""사내 포털 연동: 서비스 자동 등록과 이력 전송. 실패해도 앱은 그대로 동작한다."""

from __future__ import annotations

import asyncio
import logging
import os

import httpx

log = logging.getLogger("biz-plan.portal")

SERVICE_ID = "biz-plan"
SERVICE_NAME = "사업계획 예상손익"
SERVICE_DESC = (
    "사업계획용 예상손익을 만듭니다. 마스터 양식과 매출목표·비용 두 파일을 올리면 "
    "고객그룹별·브랜드별·월별 손익표를 보여 주고, 값을 고쳐 다시 계산할 수 있으며, "
    "고객그룹별·브랜드별·CC배부현황 엑셀 3개를 내려받을 수 있습니다."
)
# 챗에서 이 앱을 찾는 데 쓰인다. 재무팀이 실제로 쓰는 말로 채운다.
SERVICE_KEYWORDS = (
    "사업계획,예상손익,손익계획,PL,피엘,매출목표,매출계획,비용계획,판관비,공헌이익,"
    "영업이익,매출원가,원가율,고객그룹,채널별,브랜드별,월별손익,코스트센터,CC배부,"
    "간접비,공통비,배부,what-if,시뮬레이션,예산,내년계획,사업계획서"
)


def _portal_url() -> str:
    return (os.getenv("PORTAL_API_URL") or "").rstrip("/")


def _token() -> str:
    return os.getenv("AUDIT_TOKEN") or ""


# 배포하면 앱들이 한꺼번에 뜬다. 포털이 아직 안 떠 있으면 첫 시도는 거의
# 반드시 실패한다. 한 번으로 포기하면 이 앱만 관리자 화면에 안 뜨는데,
# 화면에 아무 단서가 없어서 원인을 찾는 데 한참 걸린다. 그래서 더 두드린다.
REGISTER_TRIES = int(os.getenv("REGISTER_TRIES", "10"))
REGISTER_WAIT = float(os.getenv("REGISTER_WAIT", "3"))


async def _register_once(base: str) -> None:
    body = {
        "id": SERVICE_ID,
        "name": SERVICE_NAME,
        "description": SERVICE_DESC,
        "keywords": SERVICE_KEYWORDS,
        "url": f"/{SERVICE_ID}/",
    }
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.post(f"{base}/api/services/register", json=body,
                              headers={"X-Service-Token": _token()})
        r.raise_for_status()
    log.info("포털 서비스 등록 완료 (%s)", SERVICE_ID)


async def _register_loop(base: str) -> None:
    last = ""
    for i in range(1, REGISTER_TRIES + 1):
        try:
            await _register_once(base)
            return
        except Exception as exc:  # noqa: BLE001 - 등록 실패는 치명적이지 않다
            last = f"{type(exc).__name__}: {exc}"
            if i < REGISTER_TRIES:
                await asyncio.sleep(REGISTER_WAIT)
    log.warning("포털 서비스 등록 실패 — %d번 시도했습니다. (%s) "
                "앱은 계속 동작합니다. AUDIT_TOKEN 이 포털과 같은지, "
                "포털이 떠 있는지 확인하세요.", REGISTER_TRIES, last)


async def register_service() -> None:
    """앱이 뜰 때 포털에 자기 자신을 등록한다. 기다리지 않는다."""
    base = _portal_url()
    if not base:
        log.info("PORTAL_API_URL 이 없어 서비스 등록을 건너뜁니다.")
        return
    asyncio.create_task(_register_loop(base))


async def send_audit(action: str, user: dict, detail: str = "") -> None:
    """남겨야 할 동작을 포털 이력으로 보낸다. 실패는 무시한다."""
    base = _portal_url()
    if not base:
        return
    body = {
        "service": SERVICE_NAME,
        "action": action,
        "user": user.get("id", ""),
        "dept": user.get("dept", ""),
        "detail": detail,
    }
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(f"{base}/api/audit", json=body,
                              headers={"X-Service-Token": _token()})
    except Exception as exc:  # noqa: BLE001 - 이력 전송 실패는 치명적이지 않다
        log.warning("포털 이력 전송 실패(무시하고 계속): %s", exc)
