"""서비스(앱) 저장소.

앱 목록을 코드에 하드코딩하지 않고 관리자 화면에서 등록·수정한다.
앱을 하나 추가할 때마다 코드를 고쳐 배포하는 방식은 유지되지 않는다.

접근 범위 모델:
    access = "all"        전 직원
    access = "restricted" 지정한 부서·개인만

    allowed_depts   허용 부서 (부서 전체 허용)
    allowed_users   개별 허용 (다른 부서 사람 추가)
    excluded_users  제외할 개인 (부서는 허용이지만 이 사람만 제외)
    allowed_ips     허용 IP (비어 있으면 제한 없음)

    managers        이 서비스의 담당자. 파일 삭제처럼 되돌릴 수 없는 동작을 맡는다.
                    포털 관리자는 목록에 없어도 항상 담당자로 본다.

담당자를 따로 두는 이유 — 파일 삭제를 포털 관리자만 할 수 있게 두면,
앱이 열 개가 되는 순간 IT 담당자가 모든 부서의 "이 파일 지워주세요"를
전부 받게 된다. 그 서비스를 실제로 쓰는 사람이 맡는 편이 맞다.
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
DB_PATH = os.environ.get("PORTAL_DB", "./data/portal.db")


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS services (
            id             TEXT PRIMARY KEY,
            name           TEXT NOT NULL,
            description    TEXT NOT NULL DEFAULT '',
            keywords       TEXT NOT NULL DEFAULT '',
            url            TEXT NOT NULL DEFAULT '',
            color          TEXT NOT NULL DEFAULT '#1f4e79',
            access         TEXT NOT NULL DEFAULT 'all',
            allowed_depts  TEXT NOT NULL DEFAULT '[]',
            allowed_users  TEXT NOT NULL DEFAULT '[]',
            excluded_users TEXT NOT NULL DEFAULT '[]',
            allowed_ips    TEXT NOT NULL DEFAULT '[]',
            managers       TEXT NOT NULL DEFAULT '[]',
            enabled        INTEGER NOT NULL DEFAULT 1,
            sort_order     INTEGER NOT NULL DEFAULT 0,
            created_at     TEXT NOT NULL
        );
        """)
        # 기존 DB 에 컬럼이 없으면 추가한다
        cols = {r["name"] for r in c.execute("PRAGMA table_info(services)")}
        if "managers" not in cols:
            c.execute("ALTER TABLE services ADD COLUMN managers TEXT NOT NULL DEFAULT '[]'")


def _now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    for k in ("allowed_depts", "allowed_users", "excluded_users", "allowed_ips",
              "managers"):
        try:
            d[k] = json.loads(d[k] or "[]")
        except json.JSONDecodeError:
            d[k] = []
    d["enabled"] = bool(d["enabled"])
    return d


def all_services(include_disabled: bool = True) -> list[dict]:
    q = "SELECT * FROM services"
    if not include_disabled:
        q += " WHERE enabled=1"
    q += " ORDER BY sort_order, created_at"
    with _conn() as c:
        return [_row(r) for r in c.execute(q)]


def get(sid: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM services WHERE id=?", (sid,)).fetchone()
    return _row(r) if r else None


def create(sid: str, name: str, **kw) -> None:
    with _conn() as c:
        nxt = c.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM services").fetchone()[0]
        c.execute("""
            INSERT INTO services(id,name,description,keywords,url,color,access,
                                 allowed_depts,allowed_users,excluded_users,allowed_ips,
                                 managers,enabled,sort_order,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            sid, name,
            kw.get("description", ""), kw.get("keywords", ""),
            kw.get("url", ""), kw.get("color", "#1f4e79"),
            kw.get("access", "all"),
            json.dumps(kw.get("allowed_depts", []), ensure_ascii=False),
            json.dumps(kw.get("allowed_users", []), ensure_ascii=False),
            json.dumps(kw.get("excluded_users", []), ensure_ascii=False),
            json.dumps(kw.get("allowed_ips", []), ensure_ascii=False),
            json.dumps(kw.get("managers", []), ensure_ascii=False),
            1 if kw.get("enabled", True) else 0,
            nxt, _now(),
        ))


def update(sid: str, **kw) -> bool:
    cur = get(sid)
    if not cur:
        return False
    m = {**cur, **kw}
    with _conn() as c:
        c.execute("""
            UPDATE services SET name=?, description=?, keywords=?, url=?, color=?,
                   access=?, allowed_depts=?, allowed_users=?, excluded_users=?,
                   allowed_ips=?, managers=?, enabled=?
             WHERE id=?
        """, (
            m["name"], m["description"], m["keywords"], m["url"], m["color"],
            m["access"],
            json.dumps(m["allowed_depts"], ensure_ascii=False),
            json.dumps(m["allowed_users"], ensure_ascii=False),
            json.dumps(m["excluded_users"], ensure_ascii=False),
            json.dumps(m["allowed_ips"], ensure_ascii=False),
            json.dumps(m["managers"], ensure_ascii=False),
            1 if m["enabled"] else 0,
            sid,
        ))
    return True


def delete(sid: str) -> bool:
    with _conn() as c:
        return c.execute("DELETE FROM services WHERE id=?", (sid,)).rowcount > 0


def services_of_user(user_id: str) -> list[str]:
    """이 사람이 접근 범위나 담당자로 적혀 있는 서비스 이름."""
    out = []
    with _conn() as c:
        for r in c.execute("SELECT name, allowed_users, managers FROM services"):
            for col in ("allowed_users", "managers"):
                try:
                    if user_id in json.loads(r[col] or "[]"):
                        out.append(r["name"])
                        break
                except Exception:  # noqa: BLE001
                    pass
    return out


def purge_user(user_id: str) -> list[str]:
    """지워진 계정을 접근 범위·담당자 명단에서 걷어낸다.

    ★ 이건 청소가 아니라 **보안 문제**다.
      명단에 아이디만 문자열로 남아 있어서, 나중에 같은 아이디로 계정을
      다시 만들면 그 사람이 앞사람의 권한을 그대로 물려받는다.
      "퇴사자 계정을 지웠는데 새로 온 동명이인이 인사 자료를 보더라" 가
      이렇게 생긴다. 계정을 지울 때 여기도 같이 지운다.

    되돌려주는 것은 실제로 손댄 서비스 이름들이다. 화면에 알려 준다.
    """
    touched = []
    with _conn() as c:
        for r in c.execute("SELECT id, name, allowed_users, excluded_users, managers"
                           " FROM services"):
            changed = {}
            for col in ("allowed_users", "excluded_users", "managers"):
                try:
                    cur = json.loads(r[col] or "[]")
                except Exception:  # noqa: BLE001
                    continue
                new = [u for u in cur if u != user_id]
                if len(new) != len(cur):
                    changed[col] = json.dumps(new, ensure_ascii=False)
            if changed:
                sets = ", ".join(f"{k}=?" for k in changed)
                c.execute(f"UPDATE services SET {sets} WHERE id=?",
                          (*changed.values(), r["id"]))
                touched.append(r["name"])
    return touched


def move(sid: str, direction: int) -> bool:
    """순서를 한 칸 위(-1) 또는 아래(+1)로 이동."""
    items = all_services()
    idx = next((i for i, s in enumerate(items) if s["id"] == sid), None)
    if idx is None:
        return False
    j = idx + direction
    if j < 0 or j >= len(items):
        return False
    items[idx], items[j] = items[j], items[idx]
    with _conn() as c:
        for order, s in enumerate(items):
            c.execute("UPDATE services SET sort_order=? WHERE id=?", (order, s["id"]))
    return True


def seed_examples() -> int:
    """예시 서비스를 넣는다. **자동으로 불리지 않는다.**

    처음에 이걸 자동으로 넣어 뒀더니, 실제로는 없는 앱 네 개가
    관리자 화면과 직원 첫 화면에 그대로 떠 있었다.
    "있는 줄 알고 눌렀는데 없다"는 쪽이 "처음 화면이 비어 있다"보다
    훨씬 나쁘므로, 넣고 싶을 때만 관리자 화면에서 버튼으로 넣는다.
    """
    samples = [
        ("manual", "IT 매뉴얼",
         dict(description="SAP, M365, 그룹웨어, NAS 등 사내 시스템 사용법을 단계별 화면과 함께 확인",
              keywords="매뉴얼, 사용법, 설명서, 가이드, SAP, M365, 그룹웨어, NAS, 설치, 설정",
              url="/manual/", access="all")),
        ("checklist", "업무 체크리스트",
         dict(description="수시·매일·월간·분기·연간 점검 항목과 유지보수 업체 연락처 관리",
              keywords="체크리스트, 점검, 정기점검, 유지보수, 업체, 연락처",
              url="/checklist/", access="all")),
        ("ai-report", "AI 사용량 리포트",
         dict(description="사용자별 AI 도구 사용 현황 및 월별 요금을 확인합니다",
              keywords="AI, 사용량, 비용, 요금, 사용료, 리포트",
              url="/ai-report/", access="restricted")),
        ("assets", "자산관리",
         dict(description="직원별 자산·라이선스 지급 현황, IP 관리, 렌탈 계약 만료 관리",
              keywords="자산, 노트북, PC, 라이선스, IP, 렌탈, 장비, 지급, 반납",
              url="/assets/", access="restricted")),
    ]
    added = 0
    for sid, name, kw in samples:
        if not get(sid):
            create(sid, name, **kw)
            added += 1
    return added
