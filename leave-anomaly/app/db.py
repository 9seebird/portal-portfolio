"""SQLite 저장소. 데이터 파일은 /data/app.db 한 곳에만 만든다."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "app.db"
UPLOAD_DIR = DATA_DIR / "uploads"

SCHEMA = """
-- 업로드된 데이터셋 1건(사용내역/발생내역 각 1개만 최신본을 유지)
CREATE TABLE IF NOT EXISTS dataset (
  kind         TEXT PRIMARY KEY,          -- 'usage' | 'accrual'
  filename     TEXT NOT NULL,
  stored_path  TEXT NOT NULL,
  row_count    INTEGER NOT NULL,
  payload      TEXT NOT NULL,             -- 정규화된 행 목록(JSON)
  uploaded_by  TEXT,
  uploader     TEXT,
  uploader_dept TEXT,
  uploaded_at  TEXT NOT NULL
);

-- 회사 자체 휴일(법정 공휴일 외). 고립 판정에서 '붙어 있는 휴일'로 쓰인다.
CREATE TABLE IF NOT EXISTS company_holiday (
  date TEXT PRIMARY KEY,                  -- YYYY-MM-DD
  name TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT NOT NULL
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
    return conn


def init_db() -> None:
    """데이터 폴더와 표(테이블)를 없으면 만든다."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


def save_dataset(kind: str, filename: str, stored_path: str, rows: list[dict], user: dict) -> None:
    """사용내역/발생내역 최신본을 저장한다(같은 종류는 덮어쓴다)."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO dataset (kind, filename, stored_path, row_count, payload, uploaded_by, uploader, uploader_dept, uploaded_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(kind) DO UPDATE SET filename=excluded.filename, stored_path=excluded.stored_path,"
            " row_count=excluded.row_count, payload=excluded.payload, uploaded_by=excluded.uploaded_by,"
            " uploader=excluded.uploader, uploader_dept=excluded.uploader_dept, uploaded_at=excluded.uploaded_at",
            (kind, filename, stored_path, len(rows), json.dumps(rows, ensure_ascii=False),
             user.get("id"), user.get("name"), user.get("dept"), now_iso()),
        )


def get_dataset(kind: str) -> dict | None:
    """저장된 데이터셋 1건을 꺼낸다. 없으면 None."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM dataset WHERE kind = ?", (kind,)).fetchone()
    if not row:
        return None
    return {
        "kind": row["kind"], "filename": row["filename"], "rowCount": row["row_count"],
        "rows": json.loads(row["payload"]), "uploadedAt": row["uploaded_at"],
        "uploader": row["uploader"], "uploaderDept": row["uploader_dept"],
        "storedPath": row["stored_path"],
    }


def delete_dataset(kind: str) -> bool:
    """데이터셋과 보관된 업로드 파일을 지운다."""
    existing = get_dataset(kind)
    if not existing:
        return False
    try:
        Path(existing["storedPath"]).unlink(missing_ok=True)
    except OSError:
        pass
    with connect() as conn:
        conn.execute("DELETE FROM dataset WHERE kind = ?", (kind,))
    return True


def list_company_holidays() -> list[dict]:
    """회사 자체 휴일 목록."""
    with connect() as conn:
        rows = conn.execute("SELECT date, name FROM company_holiday ORDER BY date").fetchall()
    return [{"date": r["date"], "name": r["name"]} for r in rows]


def upsert_company_holiday(date_key: str, name: str, user: dict) -> None:
    """회사 자체 휴일을 추가하거나 이름을 고친다."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO company_holiday (date, name, created_by, created_at) VALUES (?,?,?,?)"
            " ON CONFLICT(date) DO UPDATE SET name=excluded.name",
            (date_key, name, user.get("id"), now_iso()),
        )


def delete_company_holiday(date_key: str) -> bool:
    """회사 자체 휴일을 지운다."""
    with connect() as conn:
        cur = conn.execute("DELETE FROM company_holiday WHERE date = ?", (date_key,))
        return cur.rowcount > 0


def write_audit(user: dict, action: str, detail: str = "") -> None:
    """앱 자체 이력에 한 줄 남긴다."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO audit_log (at, user_id, user_name, dept, action, detail) VALUES (?,?,?,?,?,?)",
            (now_iso(), user.get("id"), user.get("name"), user.get("dept"), action, detail),
        )


def list_audit(limit: int = 100) -> list[dict]:
    """최근 이력을 최신순으로 돌려준다."""
    with connect() as conn:
        rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
