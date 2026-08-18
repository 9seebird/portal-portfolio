"""누가 쓰는지 확인한다.

이 도구는 **포털에 붙어 있지 않다.** 그래서 기본은 로그인 없이 그냥 쓰는 것이다
(STANDALONE=true). 사내망 안에서만 열리고, 하는 일이 「규칙에 맞나 봐 주기」뿐이라
막을 것이 없다. 올린 파일도 저장하지 않는다.

나중에 포털에 넣고 싶어지면 STANDALONE=false 로 바꾸기만 하면 된다.
그때부터는 포털이 앞단에서 로그인을 처리하고, 이 앱은 헤더만 읽는다.
"""

from __future__ import annotations

import os
from urllib.parse import unquote

from fastapi import HTTPException, Request

GUEST = {"id": "-", "name": "", "dept": "", "role": "user"}
DEV_USER = {"id": "hong", "name": "홍길동", "dept": "인사총무팀", "role": "admin"}


def _on(name: str, default: str = "false") -> bool:
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "yes", "on")


def current_user(request: Request) -> dict:
    """혼자 돌 때는 누구나. 포털에 붙었을 때는 포털이 붙여 준 헤더를 읽는다."""
    if _on("STANDALONE"):          # 체험판은 포털에 붙어 있으므로 기본이 false 다
        return dict(GUEST)

    user_id = request.headers.get("X-User-Id")
    if not user_id:
        if _on("DEV_MODE"):
            return dict(DEV_USER)
        raise HTTPException(status_code=401, detail="포털을 통해 접속해 주세요.")
    role = (request.headers.get("X-User-Role") or "user").strip().lower()
    return {
        "id": user_id,
        "name": unquote(request.headers.get("X-User-Name") or ""),
        "dept": unquote(request.headers.get("X-User-Dept") or ""),
        "role": "admin" if role == "admin" else "user",
    }


def require_user(request: Request) -> dict:
    return current_user(request)
