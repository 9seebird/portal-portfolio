"""장부(sqlite). 입고 이력과 앞으로 붙을 작업 이력을 **한 테이블**에 모은다.

체험판에서는 이 파일이 컨테이너 안에만 있다 (볼륨을 붙이지 않았다).
컨테이너를 다시 띄우면 사라지고, 뜰 때 예시 이력이 다시 깔린다.
남의 손이 닿은 것이 다음 사람에게 남지 않게 하려는 것이다.
사내에서 쓸 때는 compose 에 ./data 볼륨을 붙이면 그대로 쌓인다.

왜 한 테이블인가 —
  "이 서비스에 지금까지 얼마가 들었나" 를 한 줄로 뽑기 위해서다.
  입고 검수든, 나중에 붙일 코딩 에이전트 작업이든, 배포든 전부 events 에
  같은 모양으로 들어간다. 종류는 kind 로 구분한다.

      SELECT service_id, SUM(cost_krw) FROM events GROUP BY service_id;

상세 내용(검수 리포트 같은 것)은 종류별 테이블에 두고 events.ref_id 로 잇는다.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
DATA_DIR = Path(os.getenv("INTAKE_DATA_DIR", "/app/data"))
DB_PATH = DATA_DIR / "intake.db"

SCHEMA = """
-- ── 장부 ───────────────────────────────────────────────────────────
-- 사내 서비스 하나에 무슨 일이 있었는지 시간순으로 쌓인다.
CREATE TABLE IF NOT EXISTS events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  ts          TEXT    NOT NULL,          -- 2026-09-15T09:31:02+09:00
  kind        TEXT    NOT NULL,          -- intake | agent_run | deploy
  service_id  TEXT,                      -- 사내 서비스 ID (앱 폴더 이름)
  actor_id    TEXT,
  actor_name  TEXT,
  actor_dept  TEXT,
  summary     TEXT,                      -- 한 줄 요약
  status      TEXT,                      -- pass|warn|fail|requested|approved|rejected|done|error
  tokens_in   INTEGER DEFAULT 0,         -- 아래 셋은 AI 작업일 때만 채워진다
  tokens_out  INTEGER DEFAULT 0,
  cost_krw    REAL    DEFAULT 0,
  duration_ms INTEGER DEFAULT 0,
  ref_id      INTEGER,                   -- 상세 테이블의 id
  meta        TEXT                       -- 그 밖의 것 (JSON)
);
CREATE INDEX IF NOT EXISTS idx_events_service ON events(service_id);
CREATE INDEX IF NOT EXISTS idx_events_ts      ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_kind    ON events(kind);

-- ── 입고 상세 ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS intakes (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  ts          TEXT    NOT NULL,
  service_id  TEXT    NOT NULL,
  title       TEXT,                      -- 사람이 읽는 앱 이름
  note        TEXT,                      -- 제출자가 남긴 말
  actor_id    TEXT,
  actor_name  TEXT,
  actor_dept  TEXT,
  zip_name    TEXT,
  sample_id   TEXT,                     -- 체험판 예시에서 올라온 것이면 그 예시 이름
  zip_bytes   INTEGER,
  zip_sha256  TEXT,
  ok_count    INTEGER DEFAULT 0,
  warn_count  INTEGER DEFAULT 0,
  bad_count   INTEGER DEFAULT 0,
  verdict     TEXT,                      -- pass | warn | fail | error
  report      TEXT,                      -- 검수 스크립트 출력 원문
  status      TEXT    NOT NULL,          -- checked | requested | approved | rejected | superseded
  admin_id    TEXT,
  admin_name  TEXT,
  admin_note  TEXT,
  decided_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_intakes_status ON intakes(status);
CREATE INDEX IF NOT EXISTS idx_intakes_actor  ON intakes(actor_id);
"""


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init() -> None:
    with connect() as con:
        con.executescript(SCHEMA)


# ── 장부에 한 줄 남기기 ────────────────────────────────────────────
def add_event(con: sqlite3.Connection, *, kind: str, service_id: str | None,
              actor: dict | None = None, summary: str = "", status: str = "",
              tokens_in: int = 0, tokens_out: int = 0, cost_krw: float = 0.0,
              duration_ms: int = 0, ref_id: int | None = None,
              meta: dict | None = None) -> int:
    actor = actor or {}
    cur = con.execute(
        """INSERT INTO events
           (ts, kind, service_id, actor_id, actor_name, actor_dept, summary, status,
            tokens_in, tokens_out, cost_krw, duration_ms, ref_id, meta)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (now_kst(), kind, service_id, actor.get("id"), actor.get("name"), actor.get("dept"),
         summary, status, int(tokens_in), int(tokens_out), float(cost_krw),
         int(duration_ms), ref_id, json.dumps(meta or {}, ensure_ascii=False)),
    )
    return int(cur.lastrowid)


# ── 서비스별 집계 ──────────────────────────────────────────────────
def ledger(con: sqlite3.Connection, days: int = 30) -> list[dict]:
    """서비스별로 무슨 일이 몇 번 있었고 비용이 얼마인지."""
    since = (datetime.now(KST) - timedelta(days=days)).isoformat(timespec="seconds")
    rows = con.execute(
        """SELECT COALESCE(service_id, '(미지정)') AS service_id,
                  COUNT(*)                        AS events,
                  SUM(kind = 'intake')            AS intakes,
                  SUM(kind = 'agent_run')         AS agent_runs,
                  SUM(kind = 'deploy')            AS deploys,
                  SUM(tokens_in + tokens_out)     AS tokens,
                  ROUND(SUM(cost_krw), 1)         AS cost_krw,
                  MAX(ts)                         AS last_ts
             FROM events
            WHERE ts >= ?
         GROUP BY COALESCE(service_id, '(미지정)')
         ORDER BY cost_krw DESC, events DESC""",
        (since,),
    ).fetchall()
    return [dict(r) for r in rows]
