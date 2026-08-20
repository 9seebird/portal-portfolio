"""SQLite 저장소. 데이터 파일은 /data/app.db 한 곳에만 만든다."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import BUCKET_SEC, DEFAULT_MIN_RATIO

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "app.db"
UPLOAD_DIR = DATA_DIR / "uploads"

SCHEMA = """
-- 교육 과정. 보통 한 해에 하나둘이다. (예: 2026 바이브코딩 기초)
CREATE TABLE IF NOT EXISTS course (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  title       TEXT NOT NULL,
  description TEXT,
  deadline    TEXT,                      -- YYYY-MM-DD. 비어 있으면 마감 없음
  active      INTEGER NOT NULL DEFAULT 1,-- 0 이면 직원 화면에 안 보인다
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

-- 차시. 유튜브 강의 한 편, 사내 자료 한 건이 각각 하나다.
CREATE TABLE IF NOT EXISTS lesson (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  course_id    INTEGER NOT NULL REFERENCES course(id) ON DELETE CASCADE,
  seq          INTEGER NOT NULL DEFAULT 0,   -- 화면에 보이는 순서
  title        TEXT NOT NULL,
  kind         TEXT NOT NULL,                -- youtube | doc | link
  youtube_id   TEXT,                         -- kind=youtube
  url          TEXT,                         -- kind=link, 또는 doc 의 파일 경로
  note         TEXT,                         -- 한 줄 안내
  duration_sec INTEGER NOT NULL DEFAULT 0,   -- 화면이 알려준 실제 길이(초)
  min_ratio    REAL,                         -- 비면 DEFAULT_MIN_RATIO
  required     INTEGER NOT NULL DEFAULT 1,   -- 0 이면 이수 판정에서 뺀다
  created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lesson_course ON lesson(course_id, seq);

-- 사람 × 차시 진도. 이 앱의 알맹이다.
--
-- buckets 는 '0'/'1' 로 이루어진 문자열이다. 영상을 BUCKET_SEC 초짜리 칸으로
-- 쪼개서, 실제로 지나간 칸을 1 로 바꾼다. 맨 뒤로 끌어도 중간이 비어 있으면
-- 이수가 되지 않는다. 최대 위치만 기록하면 스크롤바 한 번으로 끝나 버린다.
CREATE TABLE IF NOT EXISTS progress (
  user_id      TEXT NOT NULL,
  lesson_id    INTEGER NOT NULL REFERENCES lesson(id) ON DELETE CASCADE,
  user_name    TEXT,
  dept         TEXT,
  buckets      TEXT NOT NULL DEFAULT '',
  duration_sec INTEGER NOT NULL DEFAULT 0,
  covered_sec  INTEGER NOT NULL DEFAULT 0,
  last_pos     INTEGER NOT NULL DEFAULT 0,   -- 마지막으로 보던 위치(초). 다시 열면 여기서 이어 본다
  completed    INTEGER NOT NULL DEFAULT 0,
  completed_at TEXT,
  first_at     TEXT NOT NULL,
  updated_at   TEXT NOT NULL,
  PRIMARY KEY (user_id, lesson_id)
);
CREATE INDEX IF NOT EXISTS idx_progress_lesson ON progress(lesson_id);

-- 대상자 명단. 포털에서 가져온 사본이다.
-- '들은 사람'만으로는 미수강자를 뽑을 수 없어서 '들어야 할 사람' 전체를 둔다.
CREATE TABLE IF NOT EXISTS roster (
  user_id   TEXT PRIMARY KEY,              -- 아이디. 이 앱이 사람을 알아보는 열쇠(포털 계정 이름과 맞춘다)
  emp_no    TEXT,                          -- 사번. 로그인할 때 아이디 대신 쳐도 되게 함께 둔다
  name      TEXT,
  dept      TEXT,
  pw_salt   TEXT,                          -- 비밀번호는 원문을 저장하지 않는다
  pw_hash   TEXT,
  active    INTEGER NOT NULL DEFAULT 1,
  is_admin  INTEGER NOT NULL DEFAULT 0,   -- 교육 담당자. 단독 모드에서 권한의 근거가 된다
  source    TEXT,                          -- 'portal' | 'file' — 어디서 들어온 명단인지
  synced_at TEXT NOT NULL
);

-- 앱 자체 이력(포털 이력 전송과 별개로 항상 남긴다)
CREATE TABLE IF NOT EXISTS audit_log (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  at        TEXT NOT NULL,
  user_id   TEXT,
  user_name TEXT,
  dept      TEXT,
  action    TEXT NOT NULL,
  detail    TEXT
);
"""


def now_iso() -> str:
    """UTC 기준 현재 시각 문자열."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    """SQLite 연결을 연다(행을 이름으로 꺼낼 수 있게 설정)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """데이터 폴더와 표(테이블)를 없으면 만든다. 이미 있으면 빠진 열만 더한다."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        # 먼저 만들어 둔 DB 에 나중에 생긴 열을 더한다.
        # 이렇게 해 두지 않으면 앱을 올릴 때마다 데이터를 지워야 한다.
        havep = {r["name"] for r in conn.execute("PRAGMA table_info(progress)")}
        if "last_pos" not in havep:
            conn.execute("ALTER TABLE progress ADD COLUMN last_pos INTEGER NOT NULL DEFAULT 0")
        have = {r["name"] for r in conn.execute("PRAGMA table_info(roster)")}
        for col, ddl in (("is_admin", "INTEGER NOT NULL DEFAULT 0"), ("source", "TEXT"),
                         ("emp_no", "TEXT"), ("pw_salt", "TEXT"), ("pw_hash", "TEXT")):
            if col not in have:
                conn.execute(f"ALTER TABLE roster ADD COLUMN {col} {ddl}")


def write_audit(user: dict, action: str, detail: str = "") -> None:
    """앱 안에 이력을 남긴다. 포털 전송과 별개로 항상 남는다."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO audit_log (at, user_id, user_name, dept, action, detail) "
            "VALUES (?,?,?,?,?,?)",
            (now_iso(), user.get("id"), user.get("name"), user.get("dept"), action, detail),
        )


# ---------------------------------------------------------------------------
# 과정
# ---------------------------------------------------------------------------
def list_courses(only_active: bool = False) -> list[dict]:
    """과정 목록. only_active 면 직원에게 공개된 것만."""
    sql = "SELECT * FROM course"
    if only_active:
        sql += " WHERE active = 1"
    sql += " ORDER BY active DESC, id DESC"
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql)]


def get_course(course_id: int) -> dict | None:
    """과정 한 건."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM course WHERE id = ?", (course_id,)).fetchone()
    return dict(row) if row else None


def create_course(title: str, description: str, deadline: str, active: int) -> int:
    """과정을 만든다. 만들어진 id 를 돌려준다."""
    ts = now_iso()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO course (title, description, deadline, active, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (title, description, deadline, active, ts, ts),
        )
        return int(cur.lastrowid)


def update_course(course_id: int, fields: dict) -> bool:
    """과정의 일부 항목만 고친다."""
    allowed = {"title", "description", "deadline", "active"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return False
    cols = ", ".join(f"{k} = ?" for k in sets)
    with connect() as conn:
        cur = conn.execute(
            f"UPDATE course SET {cols}, updated_at = ? WHERE id = ?",
            (*sets.values(), now_iso(), course_id),
        )
        return cur.rowcount > 0


def delete_course(course_id: int) -> bool:
    """과정과 그 아래 차시·진도를 함께 지운다."""
    with connect() as conn:
        conn.execute(
            "DELETE FROM progress WHERE lesson_id IN (SELECT id FROM lesson WHERE course_id = ?)",
            (course_id,),
        )
        conn.execute("DELETE FROM lesson WHERE course_id = ?", (course_id,))
        cur = conn.execute("DELETE FROM course WHERE id = ?", (course_id,))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# 차시
# ---------------------------------------------------------------------------
def list_lessons(course_id: int) -> list[dict]:
    """한 과정의 차시를 순서대로."""
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM lesson WHERE course_id = ? ORDER BY seq, id", (course_id,))]


def get_lesson(lesson_id: int) -> dict | None:
    """차시 한 건."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM lesson WHERE id = ?", (lesson_id,)).fetchone()
    return dict(row) if row else None


def create_lesson(course_id: int, data: dict) -> int:
    """차시를 만든다."""
    with connect() as conn:
        nxt = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM lesson WHERE course_id = ?", (course_id,)
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO lesson (course_id, seq, title, kind, youtube_id, url, note, "
            "duration_sec, min_ratio, required, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (course_id, data.get("seq") or nxt, data["title"], data["kind"],
             data.get("youtube_id"), data.get("url"), data.get("note"),
             int(data.get("duration_sec") or 0), data.get("min_ratio"),
             int(data.get("required", 1)), now_iso()),
        )
        return int(cur.lastrowid)


def update_lesson(lesson_id: int, fields: dict) -> bool:
    """차시의 일부 항목만 고친다."""
    allowed = {"seq", "title", "kind", "youtube_id", "url", "note",
               "duration_sec", "min_ratio", "required"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return False
    cols = ", ".join(f"{k} = ?" for k in sets)
    with connect() as conn:
        cur = conn.execute(f"UPDATE lesson SET {cols} WHERE id = ?",
                           (*sets.values(), lesson_id))
        return cur.rowcount > 0


def delete_lesson(lesson_id: int) -> bool:
    """차시와 그 진도를 함께 지운다."""
    with connect() as conn:
        conn.execute("DELETE FROM progress WHERE lesson_id = ?", (lesson_id,))
        cur = conn.execute("DELETE FROM lesson WHERE id = ?", (lesson_id,))
        return cur.rowcount > 0


def clear_lesson_progress(lesson_id: int) -> int:
    """한 차시의 진도를 모두 지운다.

    영상을 다른 것으로 바꿨을 때 쓴다. 그대로 두면 옛 영상에서 채운 칸이
    새 영상의 진도로 둔갑한다 — 안 본 강의가 이수로 잡히는 셈이다.
    """
    with connect() as conn:
        cur = conn.execute("DELETE FROM progress WHERE lesson_id = ?", (lesson_id,))
        return cur.rowcount


def set_lesson_duration(lesson_id: int, duration_sec: int) -> None:
    """화면이 알려준 실제 영상 길이를 저장한다(관리자가 손으로 적지 않아도 되게)."""
    with connect() as conn:
        conn.execute(
            "UPDATE lesson SET duration_sec = ? WHERE id = ? AND duration_sec <> ?",
            (duration_sec, lesson_id, duration_sec),
        )


# ---------------------------------------------------------------------------
# 진도
# ---------------------------------------------------------------------------
def _min_ratio(lesson: dict) -> float:
    """이 차시의 이수 기준 비율. 차시에 따로 없으면 기본값."""
    v = lesson.get("min_ratio")
    return float(v) if v not in (None, "") else DEFAULT_MIN_RATIO


def _bucket_count(duration_sec: int) -> int:
    """영상 길이를 칸 수로. 마지막 자투리도 한 칸으로 센다."""
    if duration_sec <= 0:
        return 0
    return (duration_sec + BUCKET_SEC - 1) // BUCKET_SEC


def get_progress(user_id: str, lesson_id: int) -> dict | None:
    """한 사람의 한 차시 진도."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM progress WHERE user_id = ? AND lesson_id = ?",
            (user_id, lesson_id),
        ).fetchone()
    return dict(row) if row else None


def progress_map(user_id: str, course_id: int) -> dict[int, dict]:
    """한 사람의 한 과정 진도를 차시 id 로 찾을 수 있게 묶어서."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT p.* FROM progress p JOIN lesson l ON l.id = p.lesson_id "
            "WHERE p.user_id = ? AND l.course_id = ?",
            (user_id, course_id),
        ).fetchall()
    return {int(r["lesson_id"]): dict(r) for r in rows}


def record_watch(user: dict, lesson: dict, prev_sec: float, pos_sec: float,
                 duration_sec: int) -> dict:
    """영상 시청 위치를 받아 지나간 칸을 채우고, 기준을 넘으면 이수로 바꾼다.

    prev_sec 는 화면이 직전에 보고한 위치다. 지금 위치와의 차이가 정상 재생
    범위(MAX_SEEK_GAP_SEC) 안이면 그 사이 칸을 전부 채우고, 그보다 멀면
    스크롤바를 끌어 건너뛴 것이므로 지금 칸 하나만 채운다.
    이 규칙 때문에 맨 뒤로 끌어도 중간 칸이 비어 이수가 되지 않는다.
    """
    from .config import MAX_SEEK_GAP_SEC

    lesson_id = int(lesson["id"])
    n = _bucket_count(duration_sec)
    if n <= 0:
        raise ValueError("영상 길이를 알 수 없습니다.")

    ts = now_iso()
    cur = get_progress(user["id"], lesson_id)
    buckets = list(cur["buckets"]) if cur else []
    # 길이가 바뀌었거나(다른 영상으로 교체) 처음이면 칸을 다시 잡는다.
    if len(buckets) != n:
        buckets = (buckets + ["0"] * n)[:n]

    def mark(sec: float) -> None:
        i = int(sec // BUCKET_SEC)
        if 0 <= i < n:
            buckets[i] = "1"

    mark(pos_sec)
    gap = pos_sec - prev_sec
    if 0 < gap <= MAX_SEEK_GAP_SEC:
        s = int(prev_sec // BUCKET_SEC)
        e = int(pos_sec // BUCKET_SEC)
        for i in range(max(0, s), min(n - 1, e) + 1):
            buckets[i] = "1"

    covered = buckets.count("1") * BUCKET_SEC
    ratio = buckets.count("1") / n
    completed = 1 if ratio >= _min_ratio(lesson) else 0
    completed_at = (cur or {}).get("completed_at")
    newly = False
    if completed and not (cur or {}).get("completed"):
        completed_at = ts
        newly = True

    with connect() as conn:
        conn.execute(
            "INSERT INTO progress (user_id, lesson_id, user_name, dept, buckets, "
            "duration_sec, covered_sec, last_pos, completed, completed_at, first_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(user_id, lesson_id) DO UPDATE SET "
            "user_name=excluded.user_name, dept=excluded.dept, buckets=excluded.buckets, "
            "duration_sec=excluded.duration_sec, covered_sec=excluded.covered_sec, "
            "last_pos=excluded.last_pos, completed=excluded.completed, "
            "completed_at=excluded.completed_at, updated_at=excluded.updated_at",
            (user["id"], lesson_id, user.get("name"), user.get("dept"), "".join(buckets),
             duration_sec, covered, int(pos_sec), completed, completed_at,
             (cur or {}).get("first_at") or ts, ts),
        )

    return {"lessonId": lesson_id, "coveredSec": covered, "durationSec": duration_sec,
            "ratio": round(ratio, 4), "completed": bool(completed),
            "completedAt": completed_at, "newlyCompleted": newly}


def resume_at(prog: dict | None, duration_sec: int) -> int:
    """다시 열었을 때 어디서부터 틀지.

    끝에 다 와서 멈춘 것이면 처음부터 트는 편이 낫다. 5초 남기고 멈춘 사람에게
    4분 55초부터 틀어 주면 아무것도 못 본다.
    """
    if not prog:
        return 0
    pos = int(prog.get("last_pos") or 0)
    if pos < 15:
        return 0
    if duration_sec and pos >= duration_sec - 20:
        return 0
    return pos


def mark_done(user: dict, lesson: dict) -> dict:
    """영상이 아닌 차시(사내 자료·바깥 링크)를 열람 완료로 표시한다.

    이쪽은 진도를 잴 방법이 없어 본인 확인에 의존한다. 그래서 사내 자료는
    영상과 섞어 두되, 이수 판정의 알맹이는 영상 차시가 지도록 구성하는 게 좋다.
    """
    ts = now_iso()
    lesson_id = int(lesson["id"])
    cur = get_progress(user["id"], lesson_id)
    newly = not (cur or {}).get("completed")
    with connect() as conn:
        conn.execute(
            "INSERT INTO progress (user_id, lesson_id, user_name, dept, buckets, "
            "duration_sec, covered_sec, last_pos, completed, completed_at, first_at, updated_at) "
            "VALUES (?,?,?,?,'',0,0,0,1,?,?,?) "
            "ON CONFLICT(user_id, lesson_id) DO UPDATE SET "
            "user_name=excluded.user_name, dept=excluded.dept, completed=1, "
            "completed_at=COALESCE(progress.completed_at, excluded.completed_at), "
            "updated_at=excluded.updated_at",
            (user["id"], lesson_id, user.get("name"), user.get("dept"),
             ts, (cur or {}).get("first_at") or ts, ts),
        )
    return {"lessonId": lesson_id, "completed": True, "newlyCompleted": newly}


# ---------------------------------------------------------------------------
# 대상자 명단
# ---------------------------------------------------------------------------
def replace_roster(people: list[dict], source: str = "portal") -> int:
    """명단을 통째로 갈아 끼운다. 퇴사자가 계속 미수강자로 남지 않게 하려는 것이다.

    **담당자 지정은 그대로 둔다.** 명단을 다시 올릴 때마다 담당자가 날아가면
    올릴 때마다 다시 지정해야 하고, 그러다 담당자가 아무도 없는 순간이 생긴다.
    올린 파일에 담당자 표시가 있으면 그쪽이 우선이다.
    """
    ts = now_iso()
    with connect() as conn:
        prev = {r["user_id"]: dict(r) for r in conn.execute(
            "SELECT user_id, is_admin, emp_no, pw_salt, pw_hash FROM roster")}
        conn.execute("DELETE FROM roster")
        rows = []
        for p in people:
            old = prev.get(p["id"], {})
            rows.append((
                p["id"],
                # 포털에는 사번이 없다. 가져올 때마다 사번이 날아가면 다시 채워야 하므로 지킨다.
                p.get("emp_no") or old.get("emp_no"),
                p.get("name"), p.get("dept"), int(p.get("active", 1)),
                int(p["is_admin"]) if p.get("is_admin") is not None else old.get("is_admin", 0),
                # 이미 비밀번호를 바꾼 사람이 있다. 명단을 다시 올린다고 되돌리지 않는다.
                old.get("pw_salt") or p.get("pw_salt"),
                old.get("pw_hash") or p.get("pw_hash"),
                source, ts))
        conn.executemany(
            "INSERT INTO roster (user_id, emp_no, name, dept, active, is_admin, "
            "pw_salt, pw_hash, source, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    return len(people)


def get_roster_person(user_id: str) -> dict | None:
    """명단에서 한 사람을 아이디로 찾는다."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM roster WHERE user_id = ?", (user_id.strip(),)).fetchone()
    return dict(row) if row else None


def find_roster_person(typed: str) -> dict | None:
    """직원이 친 값으로 한 사람을 찾는다. **아이디로 먼저, 없으면 사번으로.**

    직원은 자기 포털 아이디를 모를 수 있고 사번은 대개 안다. 둘 다 받아 주면
    안내를 덜 해도 된다. 저장은 언제나 아이디 기준이라, 내년에 포털로 옮겨도
    그동안 쌓인 진도가 그대로 이어진다.
    """
    typed = (typed or "").strip()
    if not typed:
        return None
    with connect() as conn:
        row = conn.execute("SELECT * FROM roster WHERE user_id = ?", (typed,)).fetchone()
        if not row:
            row = conn.execute(
                "SELECT * FROM roster WHERE emp_no IS NOT NULL AND emp_no <> '' AND emp_no = ?",
                (typed,)).fetchone()
    return dict(row) if row else None


def upsert_roster_person(person: dict) -> None:
    """명단에 한 사람을 더하거나 고친다. 아이디는 열쇠라 바꾸지 않는다."""
    ts = now_iso()
    with connect() as conn:
        conn.execute(
            "INSERT INTO roster (user_id, emp_no, name, dept, active, is_admin, "
            "pw_salt, pw_hash, source, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "emp_no=excluded.emp_no, name=excluded.name, dept=excluded.dept, "
            "active=excluded.active, synced_at=excluded.synced_at",
            (person["user_id"], person.get("emp_no") or None, person.get("name"),
             person.get("dept"), int(person.get("active", 1)),
             int(person.get("is_admin", 0)), person.get("pw_salt"), person.get("pw_hash"),
             person.get("source") or "manual", ts))


def set_password(user_id: str, salt: str, pw_hash: str) -> bool:
    """비밀번호를 저장한다. 원문이 아니라 소금과 해시만 남는다."""
    with connect() as conn:
        cur = conn.execute("UPDATE roster SET pw_salt = ?, pw_hash = ? WHERE user_id = ?",
                           (salt, pw_hash, user_id))
        return cur.rowcount > 0


def people_without_password() -> list[str]:
    """아직 비밀번호가 안 정해진 사람들. 명단을 올린 직후 한꺼번에 채우는 데 쓴다."""
    with connect() as conn:
        return [r["user_id"] for r in conn.execute(
            "SELECT user_id FROM roster WHERE pw_hash IS NULL OR pw_hash = ''")]


def delete_roster_person(user_id: str) -> bool:
    """명단에서 한 사람을 지운다. 그 사람의 진도 기록은 그대로 남는다."""
    with connect() as conn:
        cur = conn.execute("DELETE FROM roster WHERE user_id = ?", (user_id,))
        return cur.rowcount > 0


def emp_no_taken(emp_no: str, except_user: str = "") -> bool:
    """이미 다른 사람이 쓰고 있는 사번인지. 사번으로도 로그인하므로 겹치면 안 된다."""
    if not emp_no:
        return False
    with connect() as conn:
        row = conn.execute(
            "SELECT user_id FROM roster WHERE emp_no = ? AND user_id <> ?",
            (emp_no, except_user)).fetchone()
    return bool(row)


def set_roster_admin(user_id: str, is_admin: bool) -> bool:
    """명단에서 교육 담당자를 지정하거나 해제한다."""
    with connect() as conn:
        cur = conn.execute("UPDATE roster SET is_admin = ? WHERE user_id = ?",
                           (1 if is_admin else 0, user_id))
        return cur.rowcount > 0


def count_admins() -> int:
    """지금 담당자가 몇 명인지. 마지막 한 명을 실수로 해제하는 것을 막는 데 쓴다."""
    with connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM roster WHERE is_admin = 1 AND active = 1").fetchone()[0]


def roster_source() -> str | None:
    """지금 명단이 어디서 들어온 것인지 ('portal' | 'file')."""
    with connect() as conn:
        row = conn.execute("SELECT source FROM roster LIMIT 1").fetchone()
    return row["source"] if row else None


def list_roster(active_only: bool = True) -> list[dict]:
    """대상자 명단."""
    sql = "SELECT * FROM roster"
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY dept, name"
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql)]


def roster_synced_at() -> str | None:
    """명단을 마지막으로 가져온 시각."""
    with connect() as conn:
        row = conn.execute("SELECT MAX(synced_at) AS t FROM roster").fetchone()
    return row["t"] if row else None


# ---------------------------------------------------------------------------
# 현황 집계
# ---------------------------------------------------------------------------
def course_rows(course_id: int) -> list[dict]:
    """한 과정의 사람별 현황. 대상자 명단을 기준으로 진도를 붙인다.

    명단에 없는데 들은 사람(신규 입사 등)도 빠뜨리지 않고 함께 넣는다.
    """
    lessons = list_lessons(course_id)
    required = [l for l in lessons if l["required"]]
    req_ids = {int(l["id"]) for l in required}

    with connect() as conn:
        prog = conn.execute(
            "SELECT p.* FROM progress p JOIN lesson l ON l.id = p.lesson_id "
            "WHERE l.course_id = ?", (course_id,)
        ).fetchall()

    by_user: dict[str, list[dict]] = {}
    for r in prog:
        by_user.setdefault(r["user_id"], []).append(dict(r))

    people = {p["user_id"]: {"id": p["user_id"], "empNo": p.get("emp_no") or "",
                             "name": p["name"], "dept": p["dept"], "inRoster": True}
              for p in list_roster(active_only=True)}
    for uid, rows in by_user.items():
        if uid not in people:
            last = rows[-1]
            people[uid] = {"id": uid, "empNo": "", "name": last.get("user_name"),
                           "dept": last.get("dept"), "inRoster": False}

    # 차시 길이를 미리 꺼내 둔다. '아직 이수는 아니지만 어디까지 봤나'를 계산하는 데 쓴다.
    dur_by_lesson = {int(l["id"]): int(l["duration_sec"] or 0) for l in required}

    out = []
    for uid, person in people.items():
        rows = by_user.get(uid, [])
        done = {int(r["lesson_id"]) for r in rows if r["completed"]}
        done_req = len(req_ids & done)
        # 필수 차시가 없으면 0으로 나누지 않는다.
        pct = 0 if not req_ids else round(done_req / len(req_ids) * 100)
        started = bool(rows)
        last_at = max((r["updated_at"] for r in rows), default=None)
        finished_at = None
        if req_ids and done_req == len(req_ids):
            finished_at = max((r["completed_at"] for r in rows
                               if r["completed"] and int(r["lesson_id"]) in req_ids),
                              default=None)
        # 시청률: 차시를 다 못 채웠어도 어디까지 봤는지 보여준다.
        # 독촉 메일을 보낼 때 "아직 시작도 안 한 사람"과 "거의 다 본 사람"은 다르게 다뤄야 한다.
        seen = 0.0
        for lid in req_ids:
            row = next((r for r in rows if int(r["lesson_id"]) == lid), None)
            if not row:
                continue
            if row["completed"]:
                seen += 1.0
                continue
            d = int(row["duration_sec"] or 0) or dur_by_lesson.get(lid, 0)
            if d > 0:
                seen += min(1.0, (row["covered_sec"] or 0) / d)
        watch_pct = round(seen / len(req_ids) * 100) if req_ids else 0

        out.append({
            **person,
            "doneRequired": done_req,
            "totalRequired": len(req_ids),
            "percent": pct,
            "watchPercent": watch_pct,
            "started": started,
            "completed": bool(req_ids) and done_req == len(req_ids),
            "completedAt": finished_at,
            "lastAt": last_at,
        })
    out.sort(key=lambda x: (-x["percent"], x.get("dept") or "", x.get("name") or ""))
    return out
