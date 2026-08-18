"""인증 — 사내 포털이 앞단에서 처리한다.

바뀐 점 (자체 로그인 → 포털 헤더)
────────────────────────────────
예전에는 이 앱이 직접 아이디·비밀번호를 받고 JWT 를 발급했다.
이제는 포털 nginx 가 요청 앞에서 포털에 "이 사람이 이걸 써도 되나"를 묻고,
통과한 요청에만 아래 헤더를 붙여서 넘겨준다.

    X-User-Id      사번 또는 아이디
    X-User-Name    이름   (한글이라 퍼센트 인코딩되어 온다)
    X-User-Dept    부서   (한글이라 퍼센트 인코딩되어 온다)
    X-User-Role    admin 또는 user

권한이 없는 사람의 요청은 이 앱에 **도달조차 하지 않는다**.
직원이 X-User-Role: admin 을 직접 붙여 보내도 앞단에서 덮어쓴다.

바꾸지 않은 것
────────────
get_current_user / require_admin 의 **이름과 반환형을 그대로** 두었다.
각 라우터의 dependencies=[Depends(get_current_user)] 와
_admin=Depends(require_admin) 는 한 줄도 고칠 필요가 없다.

user.role 값도 예전 그대로 "ADMIN" / "USER" 를 쓴다.
화면의 isAdmin() 이 role === "ADMIN" 을 보고 있기 때문이다.
"""

import os
from urllib.parse import unquote

from fastapi import HTTPException, Request, status

from app.models.user import User

# 헤더가 없을 때 테스트 계정으로 동작할지. 서버에서는 반드시 false.
DEV_MODE = os.environ.get("DEV_MODE", "false").strip().lower() == "true"

_DEV_USER = {"id": "hong", "name": "홍길동", "dept": "인사총무팀", "role": "admin"}


def portal_user(request: Request) -> dict:
    """앞단(사내 포털)이 넣어준 헤더에서 사용자 정보를 읽는다."""
    uid = request.headers.get("x-user-id", "")
    if not uid:
        if DEV_MODE:
            return dict(_DEV_USER)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요합니다. 사내 포털을 통해 접속해주세요.",
        )
    return {
        "id": uid,
        # 한글은 헤더에 그대로 담을 수 없어 퍼센트 인코딩되어 온다
        "name": unquote(request.headers.get("x-user-name", "")),
        "dept": unquote(request.headers.get("x-user-dept", "")),
        "role": request.headers.get("x-user-role", "user"),
    }


def get_current_user(request: Request) -> User:
    """로그인한 사람. 라우터의 dependencies 가 이걸 부른다.

    DB 를 거치지 않는다. 계정 관리는 포털이 하고, 이 앱은 통보만 받는다.
    세션에 붙지 않은 임시 객체라 저장되지 않는다.
    """
    me = portal_user(request)
    user = User()
    user.username = me["id"]
    user.role = "ADMIN" if me["role"] == "admin" else "USER"
    user.is_active = True
    # 화면 표시용. 모델에 없는 칸이라도 파이썬 객체에는 붙는다.
    user.display_name = me["name"]
    user.dept = me["dept"]
    return user


def require_admin(request: Request) -> User:
    """삭제처럼 되돌릴 수 없는 동작 앞에서 부른다.

    누가 담당자인지는 포털 관리자 화면에서 정한다. 이 앱은 판정하지 않는다.
    """
    user = get_current_user(request)
    if user.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="담당자만 사용할 수 있습니다.",
        )
    return user


# ── 아래는 더 이상 쓰지 않는다 ────────────────────────────────
#
# hash_password / verify_password / create_access_token 은
# 자체 로그인이 없어졌으므로 필요 없다.
#
# 지우지 않고 남겨 두면 "아직 자체 로그인이 되는 줄" 알고 쓰는 코드가
# 생긴다. app/api/auth.py 의 /auth/login 과 함께 지우는 것이 안전하다.
# scripts/create_admin.py 도 더 이상 의미가 없다 (계정은 포털에 있다).
