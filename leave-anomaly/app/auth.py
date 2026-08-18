"""로그인은 사내 포털이 앞단에서 처리한다. 이 앱은 포털이 붙여 준 헤더만 읽는다."""

from __future__ import annotations

import os
from urllib.parse import unquote

from fastapi import HTTPException, Request

DEV_USER = {"id": "hong", "name": "홍길동", "dept": "인사총무팀", "role": "admin"}


def _dev_mode() -> bool:
    """환경변수 DEV_MODE 가 true 인지 확인한다."""
    return str(os.getenv("DEV_MODE", "false")).strip().lower() in ("1", "true", "yes", "on")


def current_user(request: Request) -> dict:
    """포털 헤더에서 사용자 정보를 읽는다. 헤더가 없고 DEV_MODE 도 아니면 401."""
    headers = request.headers
    user_id = headers.get("X-User-Id")
    if not user_id:
        if _dev_mode():
            return dict(DEV_USER)
        raise HTTPException(status_code=401, detail="포털을 통해 접속해 주세요.")
    role = (headers.get("X-User-Role") or "user").strip().lower()
    return {
        "id": user_id,
        "name": unquote(headers.get("X-User-Name") or ""),
        "dept": unquote(headers.get("X-User-Dept") or ""),
        "role": "admin" if role == "admin" else "user",
    }


def require_user(request: Request) -> dict:
    """접속이 확인된 사람이면 누구나 통과. 이 앱의 모든 API 가 이것을 쓴다."""
    return current_user(request)


def require_admin(request: Request) -> dict:
    """admin 권한이 필요할 때 쓰는 잠금장치. 지금은 어디에서도 쓰지 않는다.

    이 앱은 "접속한 사람은 모두 사용" 정책이라 모든 API 가 require_user 를 쓴다.
    나중에 삭제 같은 기능만 담당자로 제한하고 싶으면, main.py 의 해당 함수에서
    Depends(require_user) 를 Depends(require_admin) 으로 바꾸기만 하면 된다.
    """
    user = current_user(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="담당자(admin) 권한이 필요합니다.")
    return user
