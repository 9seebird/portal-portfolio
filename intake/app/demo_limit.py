"""체험판에서 AI 를 **진짜로** 부르기 때문에 필요한 문지기.

체험판이라고 AI 를 흉내만 내면 이 도구의 핵심(고쳐서 다시 검사까지 간다)이
안 보인다. 그래서 진짜로 부른다. 대신 지갑을 지킨다 —

  · 하루 몇 번까지 (DEMO_AI_DAILY)
  · 한 번 부르고 몇 초는 쉬기 (DEMO_AI_MIN_GAP)

세는 곳은 장부(events)다. 따로 세는 파일을 두지 않는다 — 돈이 든 기록과
「몇 번 썼나」가 두 벌이 되면 반드시 어긋난다.
체험판 db 는 컨테이너 안에만 있어서 다시 띄우면 0 부터 센다. 그걸로 충분하다
(하루 상한은 공개된 화면에서 한 사람이 통째로 쓰는 것을 막으려는 것이다).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from . import db

DAILY = int(os.getenv("DEMO_AI_DAILY", "30"))
MIN_GAP = int(os.getenv("DEMO_AI_MIN_GAP", "15"))


class Blocked(Exception):
    """더 못 부른다. 사람에게 그대로 보여 줄 수 있는 말을 담는다."""


def _today() -> str:
    return db.now_kst()[:10]


def status() -> dict:
    """{used, daily, left, wait} — 화면이 버튼을 잠글 때 쓴다."""
    with db.connect() as con:
        used = int(con.execute(
            "SELECT COUNT(*) FROM events WHERE kind = 'agent_run' AND ts LIKE ?",
            (f"{_today()}%",)).fetchone()[0])
        last = con.execute(
            "SELECT ts FROM events WHERE kind = 'agent_run' ORDER BY id DESC LIMIT 1").fetchone()
    wait = 0
    if last:
        try:
            gone = (datetime.now(db.KST) - datetime.fromisoformat(last[0])).total_seconds()
            wait = max(0, int(MIN_GAP - gone))
        except ValueError:
            wait = 0
    return {"used": used, "daily": DAILY, "left": max(0, DAILY - used), "wait": wait}


def check(*, gap: bool = True) -> None:
    """부르기 **전**에 한 번. 막히면 Blocked.

    gap=False 는 앞선 작업에 딸린 짧은 부름(변경 요약)에 쓴다. 방금 AI 수정을
    누른 사람이 그 결과를 읽으려는 길까지 「15초 기다리세요」로 막으면 안 된다.
    하루 상한은 그래도 센다.
    """
    st = status()
    if st["left"] <= 0:
        when = (datetime.now(db.KST) + timedelta(days=1)).strftime("%m월 %d일")
        raise Blocked(f"체험판은 하루 {DAILY}번까지만 AI 를 부릅니다. "
                      f"오늘은 다 썼습니다 ({when} 0시에 다시 열립니다). "
                      f"이미 AI 가 고친 이력은 목록에서 그대로 볼 수 있습니다.")
    if gap and st["wait"] > 0:
        raise Blocked(f"방금 누군가 AI 를 불렀습니다. {st['wait']}초 뒤에 다시 눌러 주세요.")
