"""사내 포털 연동: 서비스 자동 등록과 이력 전송. 실패해도 앱은 그대로 동작한다."""

from __future__ import annotations

import asyncio
import logging
import os

import httpx

log = logging.getLogger("manual-import.portal")

SERVICE_ID = "manual-import"
SERVICE_NAME = "매뉴얼 가져오기"
SERVICE_DESC = "PowerPoint 로 만든 자료를 올리면 IT 매뉴얼로 바꿔 줍니다. 담당자 전용입니다."
SERVICE_KEYWORDS = (
    "매뉴얼 가져오기,매뉴얼 등록,매뉴얼 만들기,매뉴얼 수정,매뉴얼 올리기,PPT 매뉴얼,"
    "ppt 업로드,파워포인트 매뉴얼,매뉴얼 갱신,매뉴얼 반영,매뉴얼 편집"
)


def _portal_url() -> str:
    return (os.getenv("PORTAL_API_URL") or "").rstrip("/")


def _token() -> str:
    return os.getenv("AUDIT_TOKEN") or ""


# 몇 번까지 다시 해볼지.
#
# 배포하면 앱들이 한꺼번에 뜨는데, 포털이 아직 안 떠 있으면 첫 시도는
# 거의 반드시 실패한다("Name or service not known"). 한 번으로 포기하면
# **이 앱만 관리자 화면에 안 뜬다.** 화면에는 아무 단서도 없어서
# 원인을 찾는 데 한참 걸린다. 그래서 몇 번 더 두드린다.
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
    """포털이 뜰 때까지 몇 번 더 두드린다. 실패해도 앱은 정상 동작한다."""
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
    """앱이 뜰 때 포털에 자기 자신을 등록한다.

    **기다리지 않는다.** 여기서 await 로 붙들면 포털이 늦게 뜰 때
    이 앱도 그만큼 늦게 뜬다. 뒤로 넘기고 앱은 바로 시작한다.
    """
    base = _portal_url()
    if not base:
        log.info("PORTAL_API_URL 이 없어 서비스 등록을 건너뜁니다.")
        return
    asyncio.create_task(_register_loop(base))


async def send_audit(action: str, user: dict, detail: str = "") -> None:
    """남겨야 할 동작(업로드·삭제 등)을 포털 이력으로 보낸다. 실패는 무시한다."""
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
