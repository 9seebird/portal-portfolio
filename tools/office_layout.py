# -*- coding: utf-8 -*-
"""가상 회사 「누리코스메틱」 본사 3F·4F 자리 배치도.

자리 배치도는 **표가 아니라 도면이다.** 팀 이름 줄 밑에 책상을 여섯 개씩
늘어놓으면 화면은 채워지지만, 그건 부서별 인원표를 세로로 세운 것일 뿐
「사무실」로 읽히지 않는다. 실제 사무실에는 기둥이 있고, 통로가 있고,
회의실이 벽을 등지고 있고, 팀과 팀 사이에 빈 자리가 있다.

그래서 여기에는 격자를 **한 칸씩 손으로** 적어 두었다.

    (행, 열, 세로칸, 가로칸, 종류, 이름, 팀)

행·열은 1부터 센다. CSS grid 의 grid-row / grid-column 이 1부터라
그대로 얹으면 되기 때문이다. 번호가 건너뛰는 곳은 통로다 — 빈 칸을
따로 넣지 않고 비워 두면 화면에서 저절로 통로가 된다.

종류
────
    DESK   책상. team 이 있으면 그 팀 사람이 앉고, None 이면 빈 자리다.
           빈 자리를 일부러 남겨 둔다. 자리가 꽉 찬 배치도에서는
           「이 사람 어디 앉히지」 라는 이 화면의 쓸모가 안 보인다.
    ROOM   방·설비. 회의실·탕비실·창고처럼 사람이 안 앉는 곳.
    LABEL  글자만 있는 칸. 팀 이름표와 좌석 번호.

사람을 앉히는 순서
──────────────────
DESK 칸은 **아래 목록에 적힌 차례대로** 채운다. 그래서 팀장 자리를
따로 두고 싶으면 그 칸을 팀의 다른 칸보다 먼저 적어 둔다
(경영지원팀 팀장이 '지원본부' 이름표 밑 8열에 앉는 것이 그렇다).

전부 지어낸 도면이다. 실제 사무실과 아무 관계가 없다.
"""

# (row, col, row_span, col_span, kind, label, team)
CELLS_3F = [
    # ── 방·이름표 ────────────────────────────────────────────
    (1,  3, 3, 2, "ROOM",  "임원실",        None),
    (1,  5, 1, 1, "LABEL", "재무팀",        "재무팀"),
    (1,  7, 1, 1, "LABEL", "경영지원팀",     "경영지원팀"),
    (1,  8, 1, 1, "LABEL", "지원본부",       None),
    (2, 10, 1, 1, "LABEL", "인사총무팀",     "인사총무팀"),
    (2, 11, 1, 1, "LABEL", "생산관리팀",     "생산관리팀"),
    (2, 13, 1, 1, "LABEL", "연구소",         "연구소"),
    (2, 14, 1, 3, "LABEL", "연구본부",       None),
    (2, 18, 1, 2, "ROOM",  "탕비실",         None),
    (5, 18, 2, 2, "ROOM",  "창고",           None),
    (7, 10, 1, 1, "ROOM",  "주차/택배",      None),
    (8,  1, 3, 2, "ROOM",  "임원실",         None),
    (8, 19, 2, 1, "ROOM",  "출입구",         None),
    (10, 18, 2, 2, "ROOM", "미팅룸",         None),
    (11, 1, 5, 4, "ROOM",  "임원실",         None),
    (11, 5, 5, 3, "ROOM",  "회의실",         None),
    (11, 15, 1, 1, "ROOM", "업무용PC 2ea",   None),
    (12, 15, 1, 1, "LABEL", "누리랩(주)",    None),
    (12, 16, 1, 1, "LABEL", "255",           None),
    (13, 8, 3, 2, "ROOM",  "임원실",         None),
    (13, 14, 1, 1, "ROOM", "프린트 외",      None),
    (13, 16, 1, 1, "LABEL", "254",           None),
    (14, 16, 1, 1, "LABEL", "253",           None),
    (14, 17, 2, 3, "ROOM", "임원실",         None),
    (15, 11, 1, 1, "LABEL", "프로젝트석",    None),
    (15, 12, 1, 1, "LABEL", "IT팀",          "IT팀"),
    (15, 14, 1, 1, "ROOM", "공용",           None),
    (15, 15, 1, 1, "LABEL", "누리랩",        None),

    # ── 책상 ─────────────────────────────────────────────────
    # 경영지원팀 팀장. 팀 자리보다 먼저 적어 첫 번째 사람이 앉게 한다.
    (2,  8, 1, 1, "DESK", None, "경영지원팀"),

    (2,  5, 1, 1, "DESK", None, "재무팀"),
    (3,  5, 1, 1, "DESK", None, "재무팀"),
    (4,  5, 1, 1, "DESK", None, "재무팀"),
    (5,  5, 1, 1, "DESK", None, "재무팀"),
    (6,  5, 1, 1, "DESK", None, None),

    (2,  7, 1, 1, "DESK", None, "경영지원팀"),
    (3,  7, 1, 1, "DESK", None, "경영지원팀"),
    (4,  7, 1, 1, "DESK", None, "경영지원팀"),
    (5,  7, 1, 1, "DESK", None, "경영지원팀"),
    (6,  7, 1, 1, "DESK", None, None),

    (3,  8, 1, 1, "DESK", None, "인사총무팀"),
    (4,  8, 1, 1, "DESK", None, "인사총무팀"),
    (3, 10, 1, 1, "DESK", None, "인사총무팀"),
    (4, 10, 1, 1, "DESK", None, "인사총무팀"),
    (5, 10, 1, 1, "DESK", None, None),
    (6, 10, 1, 1, "DESK", None, None),

    (3, 11, 1, 1, "DESK", None, "생산관리팀"),
    (4, 11, 1, 1, "DESK", None, "생산관리팀"),
    (5, 11, 1, 1, "DESK", None, "생산관리팀"),
    (6, 11, 1, 1, "DESK", None, "생산관리팀"),

    (3, 13, 1, 1, "DESK", None, "연구소"),
    (4, 13, 1, 1, "DESK", None, "연구소"),
    (5, 13, 1, 1, "DESK", None, "연구소"),
    (6, 13, 1, 1, "DESK", None, "연구소"),
    (7, 13, 1, 1, "DESK", None, "연구소"),
    (4, 14, 1, 1, "DESK", None, "연구소"),

    (5, 14, 1, 1, "DESK", None, None),
    (6, 14, 1, 1, "DESK", None, None),
    (7, 14, 1, 1, "DESK", None, None),
    (3, 16, 1, 1, "DESK", None, None),
    (4, 16, 1, 1, "DESK", None, None),
    (5, 16, 1, 1, "DESK", None, None),
    (6, 16, 1, 1, "DESK", None, None),
    (7, 16, 1, 1, "DESK", None, None),
    (8,  4, 1, 1, "DESK", None, None),

    (11, 12, 1, 1, "DESK", None, "IT팀"),
    (12, 12, 1, 1, "DESK", None, "IT팀"),
    (13, 12, 1, 1, "DESK", None, "IT팀"),
    (14, 12, 1, 1, "DESK", None, "IT팀"),

    (11, 14, 1, 1, "DESK", None, None),
    (12, 14, 1, 1, "DESK", None, None),
    (14, 14, 1, 1, "DESK", None, None),
    (12,  9, 1, 1, "DESK", None, None),
    (12, 11, 1, 1, "DESK", None, None),
    (13, 11, 1, 1, "DESK", None, None),
    (14, 11, 1, 1, "DESK", None, None),
    (13, 15, 1, 1, "DESK", None, None),
    (14, 15, 1, 1, "DESK", None, None),
]

CELLS_4F = [
    # ── 방·이름표 ────────────────────────────────────────────
    (1, 17, 3, 3, "ROOM",  "부사장실",       None),
    (2,  1, 1, 1, "ROOM",  "통신실",         None),
    (4,  1, 4, 1, "ROOM",  "비상 계단",      None),
    (4,  5, 1, 1, "LABEL", "해외영업팀",     "해외영업팀"),
    (4, 11, 1, 1, "LABEL", "온라인사업팀",   "온라인사업팀"),
    (4, 13, 1, 1, "ROOM",  "제품 진열장",    None),
    (4, 17, 2, 3, "ROOM",  "영업본부장실",   None),
    (5, 14, 1, 1, "LABEL", "마케팅팀",       "마케팅팀"),
    (6,  8, 1, 1, "LABEL", "국내영업팀",     "국내영업팀"),
    (7,  2, 2, 4, "ROOM",  "회의실",         None),
    (8, 16, 1, 2, "ROOM",  "회의실1",        None),
    (8, 18, 1, 2, "ROOM",  "누리문화재단",   None),
    (10, 16, 2, 2, "ROOM", "회의실2",        None),
    (11, 1, 3, 4, "ROOM",  "대표이사실",     None),
    (12, 16, 1, 2, "ROOM", "탕비실",         None),

    # ── 책상 ─────────────────────────────────────────────────
    (1,  4, 1, 1, "DESK", None, "해외영업팀"),
    (2,  4, 1, 1, "DESK", None, "해외영업팀"),
    (3,  4, 1, 1, "DESK", None, "해외영업팀"),
    (2,  6, 1, 1, "DESK", None, "해외영업팀"),
    (3,  6, 1, 1, "DESK", None, None),

    (1,  7, 1, 1, "DESK", None, "국내영업팀"),
    (2,  7, 1, 1, "DESK", None, "국내영업팀"),
    (3,  7, 1, 1, "DESK", None, "국내영업팀"),
    (4,  7, 1, 1, "DESK", None, "국내영업팀"),
    (5,  7, 1, 1, "DESK", None, "국내영업팀"),
    (1,  9, 1, 1, "DESK", None, "국내영업팀"),
    (2,  9, 1, 1, "DESK", None, "국내영업팀"),
    (3,  9, 1, 1, "DESK", None, "국내영업팀"),
    (4,  9, 1, 1, "DESK", None, None),
    (5,  9, 1, 1, "DESK", None, None),

    (1, 12, 1, 1, "DESK", None, "온라인사업팀"),
    (2, 12, 1, 1, "DESK", None, "온라인사업팀"),
    (2, 10, 1, 1, "DESK", None, "온라인사업팀"),
    (3, 10, 1, 1, "DESK", None, "온라인사업팀"),
    (4, 10, 1, 1, "DESK", None, "온라인사업팀"),
    (5, 10, 1, 1, "DESK", None, None),
    (3, 12, 1, 1, "DESK", None, None),
    (4, 12, 1, 1, "DESK", None, None),
    (5, 12, 1, 1, "DESK", None, None),

    (1, 13, 1, 1, "DESK", None, "마케팅팀"),
    (2, 13, 1, 1, "DESK", None, "마케팅팀"),
    (3, 13, 1, 1, "DESK", None, "마케팅팀"),
    (1, 15, 1, 1, "DESK", None, "마케팅팀"),
    (2, 15, 1, 1, "DESK", None, "마케팅팀"),
    (3, 15, 1, 1, "DESK", None, "마케팅팀"),
    (4, 15, 1, 1, "DESK", None, None),
]

FLOORS = [("3F", CELLS_3F), ("4F", CELLS_4F)]


def build_seats(people: list[dict]) -> list[dict]:
    """도면에 사람을 앉혀 seats 목록을 만든다.

    팀별로 재직자를 차례대로, 위 목록에 적힌 칸 순서대로 앉힌다.
    자리보다 사람이 많으면 남는 사람은 자리 없이 남는데, 그건 도면이
    잘못된 것이므로 조용히 넘기지 않고 알린다.
    """
    queue: dict[str, list[dict]] = {}
    for p in people:
        if p["status"] == "ACTIVE":
            queue.setdefault(p["department"], []).append(p)

    seats: list[dict] = []
    for floor, cells in FLOORS:
        for row, col, rspan, cspan, kind, label, team in cells:
            seat = {"floor": floor, "row_idx": row, "col_idx": col,
                    "row_span": rspan, "col_span": cspan, "kind": kind,
                    "label": label, "team": team}
            if kind == "DESK" and team:
                waiting = queue.get(team, [])
                if waiting:
                    seat["emp_no"] = waiting.pop(0)["emp_no"]
                else:
                    # 도면에 적힌 팀 자리보다 팀 인원이 적다. 빈 자리로 둔다.
                    seat["team"] = team
            seats.append(seat)

    left = {t: len(v) for t, v in queue.items() if v}
    if left:
        raise SystemExit(f"✗ 자리가 모자랍니다: {left} — office_layout.py 의 DESK 칸을 늘리세요.")
    return seats
