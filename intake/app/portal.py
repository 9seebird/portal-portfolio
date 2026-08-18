"""사내 포털 연동: 서비스 자동 등록과 이력 전송. 실패해도 앱은 그대로 동작한다."""

from __future__ import annotations

import asyncio
import logging
import os

import httpx

log = logging.getLogger("intake.portal")

SERVICE_ID = "intake"
SERVICE_NAME = "앱 입고 점검"
SERVICE_DESC = "다른 부서에서 만든 앱을 사내 포털에 붙이기 전에, 회사 표준 규칙에 맞는지 자동으로 확인합니다."
SERVICE_KEYWORDS = (
    "입고 점검,앱 점검,앱 검토,표준 규칙,규칙 확인,zip 검사,배포 전 점검,"
    "앱 제출,웍스AI,만든 앱,포털에 붙이기,check-intake"
)

REGISTER_TRIES = int(os.getenv("REGISTER_TRIES", "10"))
REGISTER_WAIT = float(os.getenv("REGISTER_WAIT", "3"))


def _portal_url() -> str:
    return (os.getenv("PORTAL_API_URL") or "").rstrip("/")


def _token() -> str:
    return os.getenv("AUDIT_TOKEN") or ""


async def _register_once(base: str) -> None:
    body = {"id": SERVICE_ID, "name": SERVICE_NAME, "description": SERVICE_DESC,
            "keywords": SERVICE_KEYWORDS, "url": f"/{SERVICE_ID}/"}
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.post(f"{base}/api/services/register", json=body,
                              headers={"X-Service-Token": _token()})
        r.raise_for_status()
    log.info("포털 서비스 등록 완료 (%s)", SERVICE_ID)


async def _register_loop(base: str) -> None:
    """포털이 뜰 때까지 몇 번 더 두드린다. 한 번에 포기하면 이 앱만 조용히 안 뜬다."""
    last = ""
    for i in range(1, REGISTER_TRIES + 1):
        try:
            await _register_once(base)
            return
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
            if i < REGISTER_TRIES:
                await asyncio.sleep(REGISTER_WAIT)
    log.warning("포털 서비스 등록 실패 — %d번 시도. (%s) 앱은 계속 동작합니다.", REGISTER_TRIES, last)


async def register_service() -> None:
    base = _portal_url()
    if not base:
        log.info("PORTAL_API_URL 이 없어 서비스 등록을 건너뜁니다.")
        return
    asyncio.create_task(_register_loop(base))


async def send_audit(action: str, user: dict, detail: str = "") -> None:
    """누가 무엇을 점검했는지 포털 이력으로 보낸다. 실패는 무시한다."""
    base = _portal_url()
    if not base:
        return
    body = {"service": SERVICE_NAME, "action": action, "user": user.get("id", ""),
            "dept": user.get("dept", ""), "detail": detail}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(f"{base}/api/audit", json=body,
                              headers={"X-Service-Token": _token()})
    except Exception as exc:  # noqa: BLE001
        log.warning("포털 이력 전송 실패(무시하고 계속): %s", exc)
