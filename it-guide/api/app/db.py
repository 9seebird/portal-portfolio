"""문서 저장. SQLite 하나에 문서 본문과 지난 판을 담는다.

### 왜 파일이 아니라 DB 인가

예전에는 화면에서 「변경사항 저장」을 눌러 index.html 을 통째로 내려받고,
그 파일을 서버에 덮어써야 반영됐다. 그래서 **서버에 파일을 올릴 수 있는
사람만** 항목을 고칠 수 있었다. 담당자가 바뀌면 아무도 못 고친다.
이제는 화면에서 고치는 즉시 여기에 쌓인다.

### 지난 판을 남기는 이유

되돌릴 길이 없으면 잘못 지운 순간이 곧 사고다. 저장할 때마다 직전 내용을
한 줄로 남겨 두고, 화면에서 골라 되돌릴 수 있게 한다.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager

DB_PATH = os.getenv("GUIDE_DB", "/data/guide.db")

# 지난 판을 몇 개까지 두나. 하루에 몇 번 고치는 화면이라 이 정도면
# 몇 달치가 남는다. 무한정 쌓으면 DB 만 커지고 목록에서 찾기도 어렵다.
HISTORY_KEEP = int(os.getenv("HISTORY_KEEP", "50"))


@contextmanager
def _conn():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS docs (
                key        TEXT PRIMARY KEY,
                data       TEXT NOT NULL,
                version    INTEGER NOT NULL DEFAULT 1,
                updated_at INTEGER NOT NULL,
                updated_by TEXT NOT NULL DEFAULT ''
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS doc_history (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                key      TEXT NOT NULL,
                data     TEXT NOT NULL,
                version  INTEGER NOT NULL,
                saved_at INTEGER NOT NULL,
                saved_by TEXT NOT NULL DEFAULT ''
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS ix_hist ON doc_history(key, id DESC)")


def get(key: str) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM docs WHERE key=?", (key,)).fetchone()
    if not row:
        return None
    return {
        "data": json.loads(row["data"]),
        "version": row["version"],
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"],
    }


def save(key: str, data, who: str, base_version: int | None) -> dict:
    """문서를 덮어쓴다.

    base_version 을 주면 그 판을 본 상태에서 고친 것으로 보고,
    그사이 남이 먼저 저장했으면 막는다(409). 두 사람이 같은 화면을
    열어 두고 각자 고칠 때 **나중에 저장한 쪽이 앞사람 것을 조용히
    지우는 일**을 막기 위해서다.
    """
    body = json.dumps(data, ensure_ascii=False)
    now = int(time.time())
    with _conn() as con:
        row = con.execute("SELECT version, data FROM docs WHERE key=?", (key,)).fetchone()
        cur = row["version"] if row else 0

        if row and base_version is not None and base_version != cur:
            raise Conflict(cur)

        if row:
            # 덮어쓰기 전에 지금 내용을 지난 판으로 남긴다
            con.execute(
                "INSERT INTO doc_history(key,data,version,saved_at,saved_by)"
                " VALUES(?,?,?,?,?)",
                (key, row["data"], cur, now, who),
            )
            con.execute(
                "UPDATE docs SET data=?, version=?, updated_at=?, updated_by=? WHERE key=?",
                (body, cur + 1, now, who, key),
            )
        else:
            con.execute(
                "INSERT INTO docs(key,data,version,updated_at,updated_by) VALUES(?,?,?,?,?)",
                (key, body, 1, now, who),
            )

        # 오래된 지난 판 정리
        con.execute(
            "DELETE FROM doc_history WHERE key=? AND id NOT IN"
            " (SELECT id FROM doc_history WHERE key=? ORDER BY id DESC LIMIT ?)",
            (key, key, HISTORY_KEEP),
        )
    return get(key)


class Conflict(Exception):
    """다른 사람이 먼저 저장했다."""

    def __init__(self, current: int):
        super().__init__(f"버전이 {current} 로 바뀌었습니다.")
        self.current = current


def history(key: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT id, version, saved_at, saved_by, length(data) AS size"
            " FROM doc_history WHERE key=? ORDER BY id DESC",
            (key,),
        ).fetchall()
    return [dict(r) for r in rows]


def history_data(key: str, hid: int):
    with _conn() as con:
        row = con.execute(
            "SELECT data FROM doc_history WHERE key=? AND id=?", (key, hid)
        ).fetchone()
    return json.loads(row["data"]) if row else None
