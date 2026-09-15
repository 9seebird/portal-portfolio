"""체험판에 깔아 두는 예시 이력.

왜 필요한가
──────────
체험판은 파일을 못 올린다. 그런데 이 앱에서 볼 것은 **검사 결과 한 장이 아니라
흐름 전체**다 — 올라온 것이 담당자 앞에 줄을 서고, 받아서 열어 보고,
승인하거나 반려하고, 그 기록이 장부에 남는다. 아무것도 없는 화면에서는
그 흐름이 보이지 않는다. 그래서 처음 뜰 때 몇 건을 깔아 둔다.

**검사 결과는 진짜다.** 사람 이름과 부서만 지어냈고, ✓△✗ 숫자와 리포트는
예시 zip 셋을 실제 검사기에 통과시켜 나온 것이다. 숫자까지 지어내면
「고칠 내용 프롬프트」가 리포트와 안 맞아서 빈 껍데기가 된다.

다음 사람에게 남지 않게
──────────────────────
장부 파일은 컨테이너 안에만 있다(볼륨을 안 붙였다). 그래서 다시 띄우면
사라지고 여기서 다시 깔린다. 그것과 별개로, 한동안 아무도 안 쓴 뒤에
들어온 사람은 **깨끗한 줄**을 봐야 한다. 앞사람이 전부 반려해 두었으면
볼 것이 없기 때문이다. DEMO_RESET_MIN 분 동안 조용했으면 다시 깐다.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from pathlib import Path

from . import db
from .checker import run

log = logging.getLogger("intake.demo")

RESET_MIN = float(os.getenv("DEMO_RESET_MIN", "30"))

# 지어낸 사람들. 데모 계정(demo)이 아닌 이름을 쓴다 —
# 보는 사람 본인이 올린 것처럼 보이면 「내가 올린 것」 목록이 이상해진다.
PEOPLE = [
    {"id": "kim", "name": "김현주", "dept": "인사총무팀"},
    {"id": "park", "name": "박지훈", "dept": "재무팀"},
    {"id": "lee", "name": "이수민", "dept": "영업기획팀"},
]

# 예시 zip 하나가 어떤 이야기로 들어가 있는지.
#   who     누가 올렸나 (PEOPLE 순번)
#   status  깔아 둘 때의 상태
#   note    제출자가 남긴 말
#   admin   담당자가 남긴 말 (처리된 것만)
STORY = {
    "회의실예약": {
        "who": 0, "status": "requested",
        "note": "층별 회의실 예약이 종이로 돌고 있어서 만들어 봤습니다. 봐 주세요.",
    },
    "출입증관리": {
        "who": 1, "status": "rejected",
        "note": "출입증 발급·회수 대장입니다.",
        "admin": "로그인을 따로 만드셨습니다. 포털 권한과 두 겹이 되니 빼 주세요.",
    },
    "비품신청": {
        "who": 2, "status": "checked",
        "note": "비품 신청받는 화면입니다.",
    },
}


async def _seed_one(samples: Path, meta: dict) -> None:
    path = samples / f'{meta["id"]}.zip'
    if not path.is_file():
        log.warning("예시 zip 이 없습니다: %s", path)
        return
    story = STORY.get(meta["id"]) or {"who": 0, "status": "checked", "note": ""}
    who = PEOPLE[story["who"] % len(PEOPLE)]

    data = path.read_bytes()
    result = await run(data, path.name)       # ★ 진짜로 검사한다
    t = result["tally"]
    status = story["status"]

    with db.connect() as con:
        cur = con.execute(
            """INSERT INTO intakes
               (ts, service_id, title, note, actor_id, actor_name, actor_dept,
                zip_name, sample_id, zip_bytes, zip_sha256,
                ok_count, warn_count, bad_count, verdict, report, status,
                admin_id, admin_name, admin_note, decided_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (db.now_kst(), meta["sid"], meta["id"], story.get("note", ""),
             who["id"], who["name"], who["dept"],
             path.name, meta["id"], len(data), hashlib.sha256(data).hexdigest(),
             t["ok"], t["warn"], t["bad"], result["verdict"], result.get("raw", ""),
             status,
             "demo" if story.get("admin") else None,
             "체험 계정" if story.get("admin") else None,
             story.get("admin"),
             db.now_kst() if story.get("admin") else None),
        )
        intake_id = int(cur.lastrowid)
        db.add_event(con, kind="intake", service_id=meta["sid"], actor=who,
                     summary=f'{meta["id"]} 제출 · 검수 {result["verdict"]}',
                     status=result["verdict"], ref_id=intake_id,
                     meta={"zip": path.name, "bytes": len(data),
                           "ok": t["ok"], "warn": t["warn"], "bad": t["bad"],
                           "demo": True})
        if status in ("requested", "approved", "rejected"):
            db.add_event(con, kind="intake", service_id=meta["sid"], actor=who,
                         summary=f'{meta["id"]} 검토 요청', status="requested",
                         ref_id=intake_id, meta={"demo": True})
        if story.get("admin"):
            db.add_event(con, kind="intake", service_id=meta["sid"],
                         actor={"id": "demo", "name": "체험 계정", "dept": "IT팀"},
                         summary=f'{meta["id"]} '
                                 f'{"승인" if status == "approved" else "반려"}'
                                 f' — {story["admin"]}',
                         status=status, ref_id=intake_id, meta={"demo": True})
        con.commit()


async def _reseed(samples: Path, metas: list[dict]) -> None:
    with db.connect() as con:
        con.execute("DELETE FROM intakes")
        con.execute("DELETE FROM events")
        con.commit()
    for meta in metas:
        try:
            await _seed_one(samples, meta)
        except Exception as exc:  # noqa: BLE001 - 예시가 안 깔려도 앱은 돈다
            log.warning("예시 이력 깔기 실패(%s): %s", meta.get("id"), exc)
    log.info("체험판 예시 이력을 다시 깔았습니다 (%d건)", len(metas))


_lock = asyncio.Lock()


async def ensure(samples: Path, metas: list[dict], force: bool = False) -> None:
    """비었거나, 한동안 조용했으면 예시를 다시 깐다.

    두 사람이 동시에 들어와도 한 번만 깔리게 잠금을 둔다. 안 그러면
    같은 줄이 두 벌 생긴다.
    """
    async with _lock:
        with db.connect() as con:
            row = con.execute("SELECT COUNT(*) AS n, MAX(ts) AS last FROM events").fetchone()
        n = int(row["n"] or 0)
        if not force and n:
            # 마지막으로 무슨 일이 있고 나서 얼마나 지났나
            last = row["last"] or ""
            try:
                from datetime import datetime
                idle = (datetime.now(db.KST) - datetime.fromisoformat(last)).total_seconds()
            except Exception:  # noqa: BLE001
                idle = 0
            if idle < RESET_MIN * 60:
                return
        await _reseed(samples, metas)
