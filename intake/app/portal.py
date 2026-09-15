"""사내 포털 연동: 서비스 자동 등록과 이력 전송. 실패해도 앱은 그대로 동작한다."""

from __future__ import annotations

import asyncio
import logging
import os
import time

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


# ── 이미 쓰고 있는 서비스 ID ───────────────────────────────────────
# 앱을 올릴 때 적는 서비스 ID 가 이미 포털에 있는 것이면 화면에서 미리
# 알려 준다. 새 앱이 남의 주소를 가져가면 nginx 에서 둘이 부딪힌다.
#
# 다만 **막지는 않는다.** 이미 있는 앱을 고쳐서 다시 올리는 경우에는
# 같은 ID 가 맞다. 맞는지 아닌지는 사람이 안다.
_ids_cache: tuple[float, dict[str, str]] | None = None
_IDS_TTL = 60.0


async def taken_ids() -> dict[str, str] | None:
    """{서비스ID: 이름}. 확인할 수 없으면 None."""
    global _ids_cache
    base = _portal_url()
    if not base:
        return None
    now = time.monotonic()
    if _ids_cache and now - _ids_cache[0] < _IDS_TTL:
        return _ids_cache[1]
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.get(f"{base}/api/services/ids",
                                 headers={"X-Service-Token": _token()})
            r.raise_for_status()
            items = r.json().get("items") or []
        got = {str(i.get("id") or "").strip(): (i.get("name") or "")
               for i in items if i.get("id")}
    except Exception as exc:  # noqa: BLE001 - 못 물어봐도 앱은 돈다
        log.warning("포털 서비스 목록 조회 실패(무시하고 계속): %s", exc)
        # 한 번이라도 받아 둔 것이 있으면 그것을 쓴다. 조금 낡은 목록이
        # "모르겠다" 보다 낫다 — None 을 주면 화면이 "아직 아무도 안 쓰는
        # 주소입니다" 라고 **틀린 말**을 하게 된다.
        return _ids_cache[1] if _ids_cache else None
    _ids_cache = (now, got)
    return got
