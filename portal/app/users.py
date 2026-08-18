"""계정 저장소.

포털 자체 계정 체계. 회원가입은 없고 관리자가 계정을 만든다.
사내 시스템에 셀프 가입을 열 이유가 없다.

비밀번호는 pbkdf2 로 해시해 저장한다. 원문은 어디에도 남기지 않는다.
외부 라이브러리를 쓰지 않으므로 추가 설치가 필요 없다.
"""

import hashlib
import os
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
DB_PATH = os.environ.get("USER_DB", "./data/users.db")

# 반복 횟수. 높을수록 안전하지만 로그인이 느려진다.
ITERATIONS = 260_000


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            pw_salt     TEXT NOT NULL,
            pw_hash     TEXT NOT NULL,
            dept        TEXT NOT NULL DEFAULT '',
            is_admin    INTEGER NOT NULL DEFAULT 0,
            active      INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT NOT NULL,
            last_login  TEXT,
            must_change INTEGER NOT NULL DEFAULT 0
        );
        """)
        # 기존 DB 에 컬럼이 없으면 추가한다
        cols = {r["name"] for r in c.execute("PRAGMA table_info(users)")}
        for col, ddl in [
            ("must_change", "INTEGER NOT NULL DEFAULT 0"),
            ("dept", "TEXT NOT NULL DEFAULT ''"),
            ("is_admin", "INTEGER NOT NULL DEFAULT 0"),
        ]:
            if col not in cols:
                c.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")


def _now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), ITERATIONS
    ).hex()


# ── 계정 관리 ────────────────────────────────────────────────
def create(user_id: str, name: str, password: str, dept: str = "",
           is_admin: bool = False, must_change: bool = True) -> None:
    """계정 생성.

    must_change 가 True 면 첫 로그인 시 비밀번호 변경 화면으로 보낸다.
    초기 비밀번호를 쉽게 줘도 되는 이유가 이것이다. 오래 남지 않는다.
    """
    salt = secrets.token_hex(16)
    with _conn() as c:
        c.execute(
            "INSERT INTO users(user_id,name,pw_salt,pw_hash,dept,is_admin,"
            "active,created_at,must_change) VALUES(?,?,?,?,?,?,1,?,?)",
            (user_id, name, salt, _hash(password, salt), dept,
             1 if is_admin else 0, _now(), 1 if must_change else 0),
        )


def set_password(user_id: str, password: str, must_change: bool = False) -> bool:
    """비밀번호 변경.

    관리자가 초기화할 때는 must_change=True 로 두어
    본인이 다시 정하도록 한다. 본인이 바꿀 때는 False.
    """
    salt = secrets.token_hex(16)
    with _conn() as c:
        cur = c.execute(
            "UPDATE users SET pw_salt=?, pw_hash=?, must_change=? WHERE user_id=?",
            (salt, _hash(password, salt), 1 if must_change else 0, user_id),
        )
    return cur.rowcount > 0


def update_profile(user_id: str, name: str | None = None,
                   dept: str | None = None, is_admin: bool | None = None) -> bool:
    cur = get(user_id)
    if not cur:
        return False
    with _conn() as c:
        c.execute("UPDATE users SET name=?, dept=?, is_admin=? WHERE user_id=?", (
            cur["name"] if name is None else name,
            cur["dept"] if dept is None else dept,
            cur["is_admin"] if is_admin is None else (1 if is_admin else 0),
            user_id,
        ))
    return True


def departments() -> list[str]:
    """등록된 부서 목록. 접근 범위 설정 화면의 체크박스에 쓴다."""
    with _conn() as c:
        rows = c.execute(
            "SELECT DISTINCT dept FROM users WHERE dept<>'' ORDER BY dept"
        ).fetchall()
    return [r["dept"] for r in rows]


def set_active(user_id: str, active: bool) -> bool:
    """퇴사·휴직 처리. 계정을 지우지 않고 비활성화한다.

    삭제하면 대화 기록의 소유자를 알 수 없게 되므로 비활성화가 맞다.
    """
    with _conn() as c:
        cur = c.execute("UPDATE users SET active=? WHERE user_id=?",
                        (1 if active else 0, user_id))
    return cur.rowcount > 0


def delete(user_id: str) -> bool:
    """계정을 지운다. 되돌릴 수 없다.

    "중지"와 나눠 둔 이유가 있다.
      중지  자리는 남기고 문만 잠근다. 휴직·대기·의심스러울 때.
      삭제  명부에서 없앤다. 퇴사처럼 다시 올 일이 없을 때.

    누가 마지막 관리자인지, 본인인지 같은 판단은 여기서 하지 않는다.
    그건 화면과 API 가 할 일이고, 여기는 지우는 일만 한다.
    """
    with _conn() as c:
        cur = c.execute("DELETE FROM users WHERE user_id=?", (user_id,))
        return cur.rowcount > 0


def get(user_id: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    return dict(r) if r else None


def all_users() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT user_id,name,dept,is_admin,active,created_at,last_login,must_change"
            " FROM users ORDER BY dept, created_at"
        ).fetchall()
    return [dict(r) for r in rows]


def count() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]


# ── 인증 ─────────────────────────────────────────────────────
def authenticate(user_id: str, password: str) -> dict | None:
    """아이디·비밀번호 확인. 실패 사유는 구분해서 알려주지 않는다.

    "아이디가 없다"와 "비밀번호가 틀렸다"를 구분해 알려주면
    존재하는 계정을 찾아내는 데 쓰인다.
    """
    u = get(user_id)
    if not u or not u["active"]:
        # 계정이 없어도 해시 계산을 수행해 응답 시간 차이를 줄인다
        _hash(password, secrets.token_hex(16))
        return None

    if not secrets.compare_digest(_hash(password, u["pw_salt"]), u["pw_hash"]):
        return None

    with _conn() as c:
        c.execute("UPDATE users SET last_login=? WHERE user_id=?", (_now(), user_id))
    return u


# 최소 길이. 첫 로그인 시 변경을 강제하므로 초기 비밀번호는 쉬워도 된다.
MIN_PASSWORD = 8


def check_password(password: str) -> str | None:
    """규칙 위반 시 사유를 돌려준다. 통과하면 None."""
    if len(password) < MIN_PASSWORD:
        return f"비밀번호는 {MIN_PASSWORD}자 이상이어야 합니다."
    return None


def suggest_password() -> str:
    """전달하기 쉬운 초기 비밀번호를 만든다.

    첫 로그인 때 바꾸게 되므로 외우기 쉬운 형태로 충분하다.
    """
    words = ["Apple", "Cloud", "Green", "Happy", "Light", "Ocean", "Peach", "Sunny"]
    return f"{secrets.choice(words)}{secrets.randbelow(9000) + 1000}!"


def admin_count(exclude: str | None = None) -> int:
    """활성 상태인 관리자 수. 마지막 관리자를 잃지 않도록 확인하는 데 쓴다."""
    return sum(
        1 for x in all_users()
        if x["active"] and x["is_admin"] and x["user_id"] != exclude
    )
