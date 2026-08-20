"""누가 접속했는지 가려내는 곳.

두 가지 방식이 있고, 환경변수 AUTH_MODE 하나로 갈린다.

    portal      챗 포털이 앞단에서 확인하고 X-User-* 헤더를 붙여 준다.
                이 앱은 헤더만 읽는다. (회사 표준 규칙 7)

    standalone  이 앱이 혼자 돈다. 아이디와 비밀번호를 받아 확인하고,
                서명한 쿠키를 하나 심는다.

**어느 쪽이든 아래 모양의 dict 를 만들어 낸다.**

    {"id": 사번, "name": 이름, "dept": 부서, "role": "admin" | "user"}

그래서 나머지 코드는 어느 쪽으로 들어왔는지 알 필요가 없다. 내년에 포털이
전 직원에게 열리면 AUTH_MODE 를 portal 로 바꾸는 것으로 끝난다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path
from urllib.parse import unquote

from fastapi import HTTPException, Request, Response

from . import db
from .config import (ADMIN_IDS, AUTH_MODE, DEFAULT_PASSWORD, LOGIN_LOCK_MINUTES,
                     LOGIN_MAX_TRIES, PASSWORD_MIN_LEN, SESSION_COOKIE, SESSION_HOURS)

DEV_USER = {"id": "hong", "name": "홍길동", "dept": "인사총무팀", "role": "admin"}


def _dev_mode() -> bool:
    """환경변수 DEV_MODE 가 true 인지 확인한다."""
    return str(os.getenv("DEV_MODE", "false")).strip().lower() in ("1", "true", "yes", "on")


def standalone() -> bool:
    """이 앱이 포털 없이 혼자 도는 중인가."""
    return AUTH_MODE != "portal"


# ---------------------------------------------------------------------------
# 쿠키에 서명하는 열쇠
# ---------------------------------------------------------------------------
def _secret() -> bytes:
    """쿠키 서명용 열쇠. 환경변수에 없으면 만들어서 /data 에 넣어 둔다.

    매번 새로 만들면 앱을 다시 띄울 때마다 모두 로그아웃된다. 그래서 파일에 남긴다.
    SECRET_KEY 를 환경변수로 주면 그쪽이 우선이다.
    """
    env = os.getenv("SECRET_KEY", "").strip()
    if env:
        return env.encode("utf-8")
    path = Path(db.DATA_DIR) / "secret.key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass  # 윈도우에서는 못 바꿔도 그만이다
    return path.read_text(encoding="utf-8").strip().encode("utf-8")


def _sign(msg: str) -> str:
    return base64.urlsafe_b64encode(
        hmac.new(_secret(), msg.encode("utf-8"), hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")


def make_token(user_id: str) -> str:
    """사번과 만료 시각에 서명해서 쿠키에 담을 문자열을 만든다."""
    exp = int(time.time()) + SESSION_HOURS * 3600
    body = f"{user_id}|{exp}"
    return base64.urlsafe_b64encode(body.encode("utf-8")).decode("ascii").rstrip("=") + "." + _sign(body)


def read_token(token: str) -> str | None:
    """쿠키를 검사해서 사번을 꺼낸다. 서명이 틀리거나 만료됐으면 None."""
    try:
        head, sig = token.split(".", 1)
        pad = "=" * (-len(head) % 4)
        body = base64.urlsafe_b64decode(head + pad).decode("utf-8")
        user_id, exp = body.rsplit("|", 1)
    except Exception:  # noqa: BLE001 - 망가진 쿠키는 그냥 로그아웃으로 본다
        return None
    if not hmac.compare_digest(sig, _sign(body)):
        return None
    if int(exp) < time.time():
        return None
    return user_id


def set_session(response: Response, user_id: str) -> None:
    """로그인 쿠키를 심는다."""
    response.set_cookie(
        SESSION_COOKIE, make_token(user_id),
        max_age=SESSION_HOURS * 3600, httponly=True, samesite="lax",
        secure=str(os.getenv("COOKIE_SECURE", "0")).strip() in ("1", "true", "on", "yes"),
        path="/",
    )


def clear_session(response: Response) -> None:
    """로그아웃."""
    response.delete_cookie(SESSION_COOKIE, path="/")


# ---------------------------------------------------------------------------
# 로그인 시도 제한
# ---------------------------------------------------------------------------
# 사번은 짐작하기 쉬우므로, 이름을 계속 바꿔 가며 넣어 보는 것을 막는다.
# 사람 수가 많지 않아 메모리에 두면 충분하다. 앱을 다시 띄우면 초기화된다.
_tries: dict[str, list[float]] = {}


def _too_many(key: str) -> bool:
    now = time.time()
    window = LOGIN_LOCK_MINUTES * 60
    hits = [t for t in _tries.get(key, []) if now - t < window]
    _tries[key] = hits
    return len(hits) >= LOGIN_MAX_TRIES


def _note_failure(key: str) -> None:
    _tries.setdefault(key, []).append(time.time())


def _clear_failures(key: str) -> None:
    _tries.pop(key, None)


# ---------------------------------------------------------------------------
# 비밀번호
# ---------------------------------------------------------------------------
# 원문은 어디에도 남기지 않는다. 사람마다 다른 소금을 섞어 20만 번 돌린 해시만 남긴다.
# 소금이 없으면 같은 비밀번호를 쓴 사람들이 같은 해시가 되어, 하나가 풀리면 전부 풀린다.
PBKDF2_ROUNDS = 200_000


def hash_password(password: str, salt: str = "") -> tuple[str, str]:
    """비밀번호를 소금과 해시로 바꾼다. 소금을 안 주면 새로 만든다."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 bytes.fromhex(salt), PBKDF2_ROUNDS)
    return salt, digest.hex()


def check_password(password: str, salt: str, expected: str) -> bool:
    """맞는 비밀번호인지. 글자 수로 시간이 달라지지 않게 비교한다."""
    if not salt or not expected:
        return False
    _, got = hash_password(password, salt)
    return hmac.compare_digest(got, expected)


def set_password(user_id: str, password: str) -> None:
    """비밀번호를 정한다."""
    salt, digest = hash_password(password)
    db.set_password(user_id, salt, digest)


def give_default_passwords() -> int:
    """비밀번호가 아직 없는 사람에게 초기 비밀번호를 넣어 준다.

    명단을 올린 직후에 한 번 돌린다. 이미 비밀번호를 바꾼 사람은 건드리지 않는다.
    """
    ids = db.people_without_password()
    for uid in ids:
        set_password(uid, DEFAULT_PASSWORD)
    return len(ids)


def validate_new_password(password: str) -> None:
    """새 비밀번호가 쓸 만한지 본다. 안 되면 이유를 알려 준다."""
    if len(password or "") < PASSWORD_MIN_LEN:
        raise HTTPException(status_code=400,
                            detail=f"비밀번호는 {PASSWORD_MIN_LEN}자 이상이어야 합니다.")
    if password.strip() != password:
        raise HTTPException(status_code=400, detail="비밀번호 앞뒤에 공백을 넣을 수 없습니다.")


# ---------------------------------------------------------------------------
# 로그인 (standalone 모드에서만 쓰인다)
# ---------------------------------------------------------------------------
def login(typed_id: str, password: str, client_ip: str = "") -> dict:
    """아이디(또는 사번)와 비밀번호를 확인한다. 맞으면 사용자 정보를 돌려준다."""
    typed_id = (typed_id or "").strip()
    if not typed_id or not password:
        raise HTTPException(status_code=400, detail="아이디와 비밀번호를 모두 입력해 주세요.")

    key = f"{client_ip}|{typed_id}"
    if _too_many(key):
        raise HTTPException(
            status_code=429,
            detail=f"비밀번호가 여러 번 틀렸습니다. {LOGIN_LOCK_MINUTES}분 뒤에 다시 시도하거나 "
                   f"교육 담당자에게 초기화를 요청해 주세요.",
        )

    # 맨 처음 — 명단이 아직 하나도 없을 때.
    # .env 의 ADMIN_IDS 에 적어 둔 아이디만, 초기 비밀번호로 들어올 수 있다.
    # 들어와서 명단을 올리면 그때부터 아래의 보통 규칙이 적용된다.
    if typed_id in ADMIN_IDS and not db.list_roster(active_only=False):
        if not hmac.compare_digest(password, DEFAULT_PASSWORD):
            _note_failure(key)
            raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
        db.replace_roster([{"id": typed_id, "name": typed_id, "dept": "", "is_admin": 1}],
                          source="bootstrap")
        set_password(typed_id, DEFAULT_PASSWORD)
        _clear_failures(key)
        return {"id": typed_id, "name": typed_id, "dept": "", "role": "admin"}

    person = db.find_roster_person(typed_id)
    # 없는 아이디와 틀린 비밀번호를 갈라서 알려주지 않는다.
    # 갈라 주면 아이디만 넣어 보고 재직 여부를 알아낼 수 있게 된다.
    if (not person or not person.get("active")
            or not check_password(password, person.get("pw_salt"), person.get("pw_hash"))):
        _note_failure(key)
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")

    _clear_failures(key)
    return _as_user(person)


def change_password(user_id: str, current: str, new: str) -> None:
    """본인이 비밀번호를 바꾼다. 지금 비밀번호를 맞게 넣어야 한다."""
    person = db.get_roster_person(user_id)
    if not person:
        raise HTTPException(status_code=404, detail="명단에서 확인되지 않습니다.")
    if not check_password(current, person.get("pw_salt"), person.get("pw_hash")):
        raise HTTPException(status_code=400, detail="지금 비밀번호가 올바르지 않습니다.")
    validate_new_password(new)
    set_password(user_id, new)


def _as_user(person: dict) -> dict:
    """명단의 한 줄을 사용자 정보 dict 로."""
    is_admin = bool(person.get("is_admin")) or person["user_id"] in ADMIN_IDS
    return {"id": person["user_id"], "name": person.get("name") or "",
            "dept": person.get("dept") or "", "role": "admin" if is_admin else "user"}


# ---------------------------------------------------------------------------
# 지금 요청을 보낸 사람
# ---------------------------------------------------------------------------
def current_user(request: Request) -> dict:
    """지금 접속한 사람. 방식에 상관없이 같은 모양의 dict 를 돌려준다."""
    # (1) 포털이 붙여 준 헤더가 있으면 언제나 그쪽이 우선이다.
    #     포털 뒤에 놓았는데 실수로 AUTH_MODE 를 안 바꿨어도 정상 동작한다.
    user_id = request.headers.get("X-User-Id")
    if user_id:
        role = (request.headers.get("X-User-Role") or "user").strip().lower()
        return {"id": user_id,
                "name": unquote(request.headers.get("X-User-Name") or ""),
                "dept": unquote(request.headers.get("X-User-Dept") or ""),
                "role": "admin" if role == "admin" else "user"}

    # (2) 단독 모드면 쿠키를 본다.
    if standalone():
        token = request.cookies.get(SESSION_COOKIE, "")
        uid = read_token(token) if token else None
        if uid:
            person = db.get_roster_person(uid)
            # 명단에서 빠졌거나(퇴사) 담당자 지정이 바뀌었으면 즉시 반영된다.
            if person and person.get("active"):
                return _as_user(person)
            raise HTTPException(status_code=401, detail="대상자 명단에서 확인되지 않습니다. 다시 로그인해 주세요.")

    # (3) 개발 중에만.
    if _dev_mode():
        return dict(DEV_USER)

    raise HTTPException(
        status_code=401,
        detail="로그인이 필요합니다." if standalone() else "포털을 통해 접속해 주세요.",
    )


def require_user(request: Request) -> dict:
    """접속이 확인된 사람이면 누구나 통과. 영상 보기·진도 기록이 이것을 쓴다."""
    return current_user(request)


def require_admin(request: Request) -> dict:
    """교육 담당자(admin)만 통과.

    과정·차시를 만들고 고치는 일, 남의 이수 현황을 보는 일이 여기에 걸린다.
    누가 담당자인지는 포털 모드에서는 포털이, 단독 모드에서는 명단이 정한다.
    """
    user = current_user(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="교육 담당자만 볼 수 있는 화면입니다.")
    return user
