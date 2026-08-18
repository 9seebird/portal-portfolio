"""부서 목록.

부서명을 손으로 입력하게 두면 "인사총무팀"과 "인사총무 팀"이 섞여
서로 다른 부서로 잡힌다. 접근 범위 판정이 부서명 기준이므로
이건 곧 "권한을 줬는데 안 보인다"로 이어진다.
그래서 부서는 여기에 등록된 것 중에서만 고르게 한다.

### 왜 조인을 쓰지 않는가

부서를 번호(id)로 참조하고 조인하는 방식이 교과서적이긴 하다.
다만 이 규모(직원 수십 명, 부서 열 개 안팎)에서는

- DB 파일을 열어봤을 때 `dept` 칸에 "인사총무팀"이라고 적혀 있는 편이
  `dept_id=3` 보다 문제를 훨씬 빨리 찾게 해준다
- 조인이 users, services 양쪽에 붙으면 접근 판정 코드가 복잡해진다
- 부서명 변경은 몇 년에 한 번이고, 그때 `rename()` 이 관련 테이블을
  한 번에 고쳐 준다

교과서가 조인을 권하는 이유는 "이름이 바뀌면 여기저기 흩어진 값이
따로 놀기 때문"인데, 그 문제는 rename() 하나로 막을 수 있다.
따라서 이름을 그대로 저장하되 **입력 경로를 목록으로 좁히는** 쪽을 택했다.
"""

import os
import sqlite3
from pathlib import Path

DB_PATH = os.environ.get("PORTAL_DB", "./data/portal.db")


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS departments (
            name       TEXT PRIMARY KEY,
            sort_order INTEGER NOT NULL DEFAULT 0
        );
        """)


def all_depts() -> list[str]:
    with _conn() as c:
        return [r["name"] for r in
                c.execute("SELECT name FROM departments ORDER BY sort_order, name")]


def exists(name: str) -> bool:
    with _conn() as c:
        return c.execute("SELECT 1 FROM departments WHERE name=?",
                         (name,)).fetchone() is not None


def create(name: str) -> bool:
    name = name.strip()
    if not name or exists(name):
        return False
    with _conn() as c:
        nxt = c.execute(
            "SELECT COALESCE(MAX(sort_order),0)+1 FROM departments").fetchone()[0]
        c.execute("INSERT INTO departments(name,sort_order) VALUES(?,?)", (name, nxt))
    return True


def rename(old: str, new: str) -> bool:
    """부서명 변경.

    부서명이 저장된 곳을 **한 번에 모두** 고친다.
    한 군데라도 빠뜨리면 그 순간부터 값이 따로 놀기 시작한다.
      - departments.name
      - users.dept
      - services.allowed_depts (JSON 배열 안의 문자열)
    """
    new = new.strip()
    if not new or old == new or not exists(old) or exists(new):
        return False

    with _conn() as c:
        c.execute("UPDATE departments SET name=? WHERE name=?", (new, old))

    # 서비스의 허용 부서 목록
    from . import services
    for s in services.all_services():
        depts = s.get("allowed_depts") or []
        if old in depts:
            services.update(s["id"],
                            allowed_depts=[new if d == old else d for d in depts])

    # 사용자 소속
    from . import users
    with users._conn() as c:  # noqa: SLF001 — 같은 프로젝트 내부 접근
        c.execute("UPDATE users SET dept=? WHERE dept=?", (new, old))
    return True


def usage(name: str) -> dict:
    """이 부서를 쓰고 있는 곳. 삭제 전에 확인시켜 준다."""
    from . import services, users
    return {
        "users": [u["user_id"] for u in users.all_users() if u["dept"] == name],
        "services": [s["name"] for s in services.all_services()
                     if name in (s.get("allowed_depts") or [])],
    }


def delete(name: str) -> bool:
    """부서 삭제.

    쓰는 곳이 남아 있으면 지우지 않는다. 지워 버리면 그 사람들의
    소속이 빈칸이 되어 아무 서비스도 못 보게 된다. 조용히 권한이
    사라지는 쪽이 오류 메시지보다 훨씬 나쁘다.
    """
    u = usage(name)
    if u["users"] or u["services"]:
        return False
    with _conn() as c:
        return c.execute("DELETE FROM departments WHERE name=?", (name,)).rowcount > 0


def move(name: str, direction: int) -> bool:
    items = all_depts()
    i = items.index(name) if name in items else -1
    if i < 0:
        return False
    j = i + direction
    if j < 0 or j >= len(items):
        return False
    items[i], items[j] = items[j], items[i]
    with _conn() as c:
        for order, d in enumerate(items):
            c.execute("UPDATE departments SET sort_order=? WHERE name=?", (order, d))
    return True


def sync_from_users() -> int:
    """계정에 있는데 부서 목록에 없는 부서를 끌어와 등록한다.

    부서 테이블을 도입하기 전에 만든 계정들을 위한 보정이다.
    서버가 뜰 때 한 번 돌면 기존 부서가 그대로 목록에 들어온다.
    """
    from . import users
    known = set(all_depts())
    added = 0
    for d in sorted({u["dept"] for u in users.all_users() if u["dept"]} - known):
        if create(d):
            added += 1
    return added
