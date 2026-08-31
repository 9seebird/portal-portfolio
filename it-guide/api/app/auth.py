"""로그인은 사내 포털이 앞단에서 처리한다. 이 앱은 포털이 붙여 준 헤더만 읽는다."""

from __future__ import annotations

import os
from urllib.parse import unquote

from fastapi import HTTPException, Request

DEV_USER = {"id": "hong", "name": "홍길동", "dept": "인사총무팀", "role": "admin"}

# 문서 하나에 붙는 이름. 앞단 nginx 가 경로에 맞춰 X-Doc-Key 로 넣어 준다.
#
# ★ 경로에서 받지 않고 헤더로 받는 이유.
#   경로에서 받으면 체크리스트 담당자가 /checklist/api/doc/ito-cost 처럼
#   **남의 문서 이름을 적어 보낼 수 있다.** 그러면 ITO 담당자가 아닌
#   사람이 ITO 비용처리를 고치게 된다. 헤더는 nginx 가 넣으므로
#   브라우저가 바꿔 보낼 수 없다.
DOC_KEYS = {"checklist", "ito-cost"}


def _dev_mode() -> bool:
    return str(os.getenv("DEV_MODE", "false")).strip().lower() in ("1", "true", "yes", "on")


def current_user(request: Request) -> dict:
    """포털 헤더에서 사용자 정보를 읽는다. 헤더가 없고 DEV_MODE 도 아니면 401."""
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        if _dev_mode():
            return dict(DEV_USER)
        raise HTTPException(status_code=401, detail="포털을 통해 접속해 주세요.")
    role = (request.headers.get("X-User-Role") or "user").strip().lower()
    return {
        "id": user_id,
        "name": unquote(request.headers.get("X-User-Name") or ""),
        "dept": unquote(request.headers.get("X-User-Dept") or ""),
        "role": "admin" if role == "admin" else "user",
    }


def doc_key(request: Request) -> str:
    """어느 문서를 다루는 요청인지. nginx 가 넣어 준 값만 믿는다."""
    key = (request.headers.get("X-Doc-Key") or "").strip()
    if key not in DOC_KEYS:
        # 헤더가 없다는 것은 nginx 설정이 빠졌다는 뜻이다. 조용히 넘기면
        # 엉뚱한 문서에 쓰게 되므로 여기서 분명히 멈춘다.
        raise HTTPException(
            status_code=400,
            detail="문서 이름을 알 수 없습니다. nginx 설정에 X-Doc-Key 가 빠졌습니다.",
        )
    return key


def require_user(request: Request) -> dict:
    """접속이 확인된 사람이면 통과. 읽기는 여기까지만 있으면 된다."""
    return current_user(request)


def require_manager(request: Request) -> dict:
    """고치는 것은 담당자만.

    포털이 X-User-Role 에 admin 을 넣어 주는 사람은 두 부류다.
      · 포털 관리자
      · 관리자 화면에서 그 서비스의 **담당자**로 지정된 사람
    그래서 담당자를 바꾸는 일은 포털 관리자 화면에서만 하면 된다.
    인수인계 때 후임자를 담당자로 지정하면 그날부터 고칠 수 있다.
    """
    user = current_user(request)
    if user["role"] != "admin":
        raise HTTPException(
            status_code=403,
            detail="담당자만 고칠 수 있습니다. 포털 관리자에게 담당자 지정을 요청하세요.",
        )
    return user
