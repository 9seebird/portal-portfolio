"""인증 — JWT 기반.

흐름:
    로그인(아이디/비밀번호) → JWT 발급 → 이후 요청은 Authorization 헤더로

JWT 는 서버에 저장하지 않는다. 서명만 검증하면 되므로 조회가 없다.
대신 즉시 무효화가 안 되므로 만료를 짧게 둔다(기본 12시간).
퇴사 처리는 users.set_active(False) 로 하고, 다음 로그인부터 차단된다.
발급된 토큰까지 즉시 끊어야 하면 아래 '즉시 차단' 주석을 참고할 것.
"""

import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Header, HTTPException, Request

from . import users
from .registry import User

JWT_SECRET = os.environ.get("JWT_SECRET", "")
JWT_ALG = "HS256"
JWT_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "12"))

# 옆 서비스(ai-report 등)를 위한 쿠키 이름.
#
# 챗 화면은 SPA 라 토큰을 헤더에 담아 보내면 되지만, 직원이 /ai-report/ 로
# 이동하면 그건 다른 서버가 처리하는 일반 페이지 이동이라 헤더를 붙일 수 없다.
# 그래서 로그인할 때 같은 JWT 를 쿠키로도 심는다.
#   HttpOnly  — 자바스크립트가 못 읽는다. XSS 로 토큰이 새 나가는 경로를 막는다
#   SameSite=Lax — 다른 사이트에서 넘어온 요청에는 붙지 않는다
COOKIE_NAME = "portal_token"
# HTTPS 로 전환하면 .env 에 COOKIE_SECURE=1 을 넣는다.
# 사내망 http 에서 1 로 두면 쿠키가 아예 저장되지 않으므로 기본은 0.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0").strip() in ("1", "true", "on", "yes")


def _secret() -> str:
    if not JWT_SECRET or len(JWT_SECRET) < 16:
        raise RuntimeError(
            "JWT_SECRET 이 설정되지 않았거나 너무 짧습니다. "
            ".env 에 임의의 긴 문자열을 넣으세요."
        )
    return JWT_SECRET


def issue_token(u: dict) -> tuple[str, int]:
    """로그인 성공 시 JWT 발급. (토큰, 만료까지 남은 초)"""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=JWT_HOURS)
    payload = {
        "sub": u["user_id"],
        "name": u["name"],
        "dept": u.get("dept", ""),
        "adm": bool(u.get("is_admin")),
        "chg": bool(u.get("must_change")),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALG), JWT_HOURS * 3600


def decode_token(token: str) -> dict:
    """검증 실패 시 예외를 던진다."""
    return jwt.decode(token, _secret(), algorithms=[JWT_ALG])


def client_ip(request: Request) -> str | None:
    """접속 IP.

    nginx 뒤에 두면 request.client.host 가 항상 127.0.0.1 이 되므로
    X-Forwarded-For 의 맨 앞 값을 먼저 본다. 그 헤더는 위조가 가능하니
    nginx 에서 proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    로 덮어쓰도록 설정해 둘 것. 그래야 클라이언트가 넣은 값이 남지 않는다.
    """
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def set_login_cookie(response, token: str) -> None:
    """로그인 쿠키를 심는다. 옆 서비스가 이 쿠키로 사용자를 확인한다."""
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=JWT_HOURS * 3600,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",          # /ai-report/ 로 이동해도 함께 간다
    )


def clear_login_cookie(response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


async def current_user(request: Request,
                       authorization: str = Header(default="")) -> User:
    """FastAPI 의존성.

    두 경로를 모두 받는다.
      1. Authorization: Bearer <JWT>  — 챗 화면(SPA)이 쓴다
      2. portal_token 쿠키            — 옆 서비스와 일반 페이지 이동이 쓴다
    헤더를 먼저 본다. 로그아웃 직후 쿠키가 남아 있어도 헤더가 우선이다.
    """
    token = ""
    if authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    else:
        token = request.cookies.get(COOKIE_NAME, "").strip()

    if not token:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    try:
        p = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="로그인이 만료되었습니다. 다시 로그인해 주세요.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="유효하지 않은 인증 정보입니다.")

    # 토큰이 아니라 DB 를 기준으로 삼는다.
    #
    # JWT 안의 값만 믿으면 관리자 권한을 회수해도, 부서를 바꿔도,
    # 퇴사 처리를 해도 토큰이 만료되는 12시간 동안 예전 권한이 그대로 산다.
    # 화면에서 관리 메뉴가 사라지지 않는 정도가 아니라 관리자 API 가
    # 계속 열려 있다는 뜻이므로 이건 편의 문제가 아니라 구멍이다.
    #
    # 비용은 요청당 SQLite 조회 한 번이다. 같은 서버의 파일이라
    # 밀리초 단위이고, 이 규모에서 체감되지 않는다.
    # 사용자가 수백 명을 넘어 이 조회가 부담이 되면 그때
    # 짧은 캐시(수십 초)를 두면 된다. 토큰 수명을 늘리는 방향은 아니다.
    u = users.get(p["sub"])
    if not u or not u["active"]:
        raise HTTPException(status_code=401, detail="사용할 수 없는 계정입니다.")

    return User(user_id=u["user_id"], name=u["name"],
                dept=u["dept"], is_admin=bool(u["is_admin"]),
                ip=client_ip(request))


async def admin_user(request: Request,
                     authorization: str = Header(default="")) -> User:
    """관리자 전용 엔드포인트에 사용."""
    u = await current_user(request, authorization)
    if not u.is_admin:
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    return u
