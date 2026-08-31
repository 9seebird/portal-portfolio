"""사내 포털에 이력을 보낸다. 실패해도 앱은 그대로 동작한다.

서비스 등록은 이 앱이 하지 않는다. it-guide 는 화면이 여섯 개라
compose 의 guide-register 컨테이너가 한꺼번에 등록한다.
여기서 또 등록하면 같은 서비스를 두 곳에서 손대게 된다.
"""

from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger("guide-api.portal")

SERVICE_NAMES = {"checklist": "IT 운영 체크리스트", "ito-cost": "ITO 비용처리"}


async def send_audit(key: str, action: str, user: dict, detail: str = "") -> None:
    base = (os.getenv("PORTAL_API_URL") or "").rstrip("/")
    token = os.getenv("AUDIT_TOKEN") or ""
    if not base or not token:
        return
    body = {
        "service": SERVICE_NAMES.get(key, key),
        "action": action,
        "user": user.get("id", ""),
        "dept": user.get("dept", ""),
        "detail": detail,
    }
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(f"{base}/api/audit", json=body,
                              headers={"X-Service-Token": token})
    except Exception as exc:  # noqa: BLE001 - 이력 전송 실패는 치명적이지 않다
        log.warning("포털 이력 전송 실패(무시하고 계속): %s", exc)
