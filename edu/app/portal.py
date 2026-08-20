"""챗 포털 연동: 서비스 자동 등록 · 이력 전송 · 직원 명단 가져오기.

등록과 이력은 실패해도 앱이 그대로 동작한다.
"""

from __future__ import annotations

import asyncio
import logging
import os

import httpx

from .config import SERVICE_DESC, SERVICE_ID, SERVICE_KEYWORDS, SERVICE_NAME

log = logging.getLogger("edu.portal")


def _portal_url() -> str:
    return (os.getenv("PORTAL_API_URL") or "").rstrip("/")


def _token() -> str:
    return os.getenv("AUDIT_TOKEN") or ""


# 몇 번까지 다시 해볼지.
#
# 배포하면 앱들이 한꺼번에 뜨는데, 포털이 아직 안 떠 있으면 첫 시도는
# 거의 반드시 실패한다. 한 번으로 포기하면 이 앱만 관리자 화면에 안 뜨고,
# 화면에는 아무 단서도 없어서 원인을 찾는 데 한참 걸린다.
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
    """앱이 뜰 때 포털에 자기 자신을 등록한다. 기다리지 않고 뒤로 넘긴다."""
    base = _portal_url()
    if not base:
        log.info("PORTAL_API_URL 이 없어 서비스 등록을 건너뜁니다.")
        return
    asyncio.create_task(_register_loop(base))


async def send_audit(action: str, user: dict, detail: str = "") -> None:
    """남겨야 할 동작(과정 생성·삭제·명단 갱신 등)을 포털 이력으로 보낸다. 실패는 무시한다."""
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


class RosterError(RuntimeError):
    """직원 명단을 가져오지 못했을 때. 사람이 읽을 수 있는 이유를 담는다."""


async def login_portal(user_id: str, password: str) -> str:
    """포털에 한 번 로그인해서 토큰만 받아 온다.

    단독 모드에서는 브라우저에 포털 쿠키가 없다(포털을 안 거치고 들어왔으니까).
    그래서 명단을 가져올 때 담당자에게 포털 관리자 아이디·비밀번호를 한 번 물어
    이 함수로 토큰을 받고, 명단을 받아 온 뒤 토큰은 그대로 버린다.
    **비밀번호는 저장하지도, 기록에 남기지도 않는다.**
    """
    base = _portal_url()
    if not base:
        raise RosterError("PORTAL_API_URL 이 설정되어 있지 않습니다. "
                          "포털이 없는 환경이면 명단 파일을 올려 주세요.")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{base}/api/login",
                                  json={"user_id": user_id, "password": password})
    except Exception as exc:  # noqa: BLE001
        raise RosterError(f"포털에 연결하지 못했습니다: {type(exc).__name__}") from exc
    if r.status_code == 401:
        raise RosterError("포털 아이디 또는 비밀번호가 올바르지 않습니다.")
    if r.status_code != 200:
        raise RosterError(f"포털 로그인이 {r.status_code} 를 돌려주었습니다.")
    data = r.json()
    if not data.get("user", {}).get("is_admin"):
        raise RosterError("포털 관리자 계정이어야 직원 명단을 가져올 수 있습니다.")
    return data.get("token") or ""


async def fetch_roster_by_login(user_id: str, password: str) -> list[dict]:
    """포털 관리자 계정으로 로그인해서 직원 명단을 가져온다(단독 모드용)."""
    token = await login_portal(user_id, password)
    return await fetch_roster(token)


async def fetch_roster(portal_token: str) -> list[dict]:
    """포털의 직원 명단을 그대로 가져온다.

    미수강자 명단을 뽑으려면 '들은 사람'뿐 아니라 '들어야 할 사람' 전체가 필요하다.
    그 명단은 포털이 이미 갖고 있으므로 여기서 따로 관리하지 않고 그때그때 가져온다.

    포털의 /api/admin/users 는 **포털 관리자 본인**만 부를 수 있다. 서비스 토큰으로는
    안 되고, 관리자가 브라우저로 접속했을 때 딸려 오는 portal_token 쿠키를 그대로
    전달해야 한다. 그래서 이 함수는 화면에서 관리자가 버튼을 눌렀을 때만 불린다.
    """
    base = _portal_url()
    if not base:
        raise RosterError("PORTAL_API_URL 이 설정되어 있지 않습니다.")
    if not portal_token:
        raise RosterError(
            "포털 로그인 정보를 찾지 못했습니다. 포털에 다시 로그인한 뒤 시도해 주세요."
        )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{base}/api/admin/users",
                                 headers={"Cookie": f"portal_token={portal_token}",
                                          "Authorization": f"Bearer {portal_token}"})
    except Exception as exc:  # noqa: BLE001
        raise RosterError(f"포털에 연결하지 못했습니다: {type(exc).__name__}") from exc

    if r.status_code in (401, 403):
        raise RosterError(
            "포털 관리자 권한이 필요합니다. 이 서비스의 담당자여도 포털 전체 관리자가 "
            "아니면 직원 명단을 가져올 수 없습니다."
        )
    if r.status_code != 200:
        raise RosterError(f"포털이 {r.status_code} 를 돌려주었습니다.")

    try:
        users = r.json().get("users", [])
    except Exception as exc:  # noqa: BLE001
        raise RosterError("포털 응답을 읽지 못했습니다.") from exc

    out = []
    for u in users:
        uid = str(u.get("user_id") or u.get("id") or "").strip()
        if not uid:
            continue
        active = u.get("active", u.get("is_active", True))
        out.append({
            "id": uid,
            "name": str(u.get("name") or "").strip(),
            "dept": str(u.get("dept") or "").strip(),
            "active": 0 if active in (0, False, "0", "false") else 1,
            # 포털 관리자는 교육 담당자로 시작한다. 담당자 화면에서 따로 바꿀 수 있다.
            "is_admin": 1 if u.get("is_admin") in (1, True, "1", "true") else None,
        })
    return out
