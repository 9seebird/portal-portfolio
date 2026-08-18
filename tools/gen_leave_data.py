# -*- coding: utf-8 -*-
"""연차 이상패턴 앱에 넣을 가짜 「사용내역 · 발생내역」 엑셀을 만든다.

이 앱은 **이상한 것을 찾아 주는 앱**이다. 그러니 평범한 데이터만 넣으면
화면에 아무것도 안 뜨고, 방문자는 앱이 고장 난 줄 안다.

그래서 찾아야 할 것을 **일부러 심는다.**

    위험      21일 안에 고립 연차 3번 (화·수·목 전일) → 점수 3.0
    검토      21일 안에 고립 연차 3번인데 요일 가중치가 낮음
    저사용    발생 15일 중 1일만 씀 (연차 쌓아두기)
    급증      최근 60일에 몰아서 8일

「고립」은 앞뒤로 휴일·주말·본인 연차가 붙지 않은 평일 연차를 말한다.
그래서 금요일·월요일은 주말에 붙어 고립이 아니고, 화·수·목이 고립이 된다.
가중치도 화·수·목이 1.0 으로 제일 높다 — 붙여 쉬는 것이 아니라
**한가운데를 비우는 것**이 눈에 띄는 신호라서다.

전부 지어낸 것이다. 실제 사람·기록과 무관하다.
"""

import random
from datetime import date, timedelta

import demo_company as C

TODAY = date.today()
START = date(TODAY.year, 1, 1)      # 올해 1월 1일부터

USAGE_HEADER = ["사원번호", "직원", "조직들", "휴가 그룹", "휴가 유형",
                "시작 시간", "차감 일수"]
ACCRUAL_HEADER = ["사원번호", "이름", "본조직", "휴가 그룹", "상태",
                  "발생 일수", "사용한 휴가 일수", "남은 휴가 일수",
                  "발생 시점", "만료 시점"]

# 회사 자체 휴일. 「연차가 휴일에 붙었는가」를 보는 기능이 있어서
# 하나도 없으면 그 판정이 무슨 뜻인지 화면에서 안 드러난다.
COMPANY_HOLIDAYS = [
    ("창립기념일", (5, 20)),
    ("여름 단체휴무", (8, 1)),
]


def _weekday_on_or_after(d: date, wd: int) -> date:
    """d 이후(포함) 첫 번째 wd 요일. wd 는 0=월 … 6=일."""
    return d + timedelta(days=(wd - d.weekday()) % 7)


def build():
    r = random.Random(C.SEED + 2)
    people = [p for p in C.people() if p["status"] == "ACTIVE"]

    usage: list[list] = []
    accrual: list[list] = []

    def take(p, day: date, kind: str = "full"):
        """연차 한 건을 적는다. kind 는 full / am / pm."""
        if kind == "full":
            usage.append([p["emp_no"], p["name"], p["department"], "연차휴가",
                          "연차", f"{day.isoformat()} 09:00", 1])
        elif kind == "am":
            usage.append([p["emp_no"], p["name"], p["department"], "연차휴가",
                          "오전반차", f"{day.isoformat()} 09:00", 0.5])
        else:
            usage.append([p["emp_no"], p["name"], p["department"], "연차휴가",
                          "오후반차", f"{day.isoformat()} 14:00", 0.5])

    # ── 평범한 사람들 ───────────────────────────────────────
    # 대부분은 금요일·월요일에 붙여 쉬거나 연달아 며칠 쉰다.
    # 그래야 「고립」이 진짜로 드문 일이 되고, 걸린 사람이 의미를 갖는다.
    #
    # ★ 여기 비율을 잘못 잡으면 앱이 쓸모없어 보인다.
    #   처음에는 평일(화·목)을 자주 넣었더니 50명 중 12명이 「위험」으로
    #   떴다. 넷 중 하나가 위험이면 그건 경고가 아니라 소음이고,
    #   보는 사람은 기준을 안 믿게 된다.
    #   금·월에 붙여 쉬거나 이틀 연속으로 쉬는 쪽을 확 늘려서
    #   지금은 50명 중 위험 3 · 검토 6 · 관찰 6 이다.
    used_days: dict[str, float] = {}
    for p in people:
        n = r.randint(3, 7)
        taken: set[date] = set()
        for _ in range(n):
            for _try in range(30):
                day = START + timedelta(days=r.randint(0, (TODAY - START).days))
                # 금(4) 또는 월(0) 위주. 붙여 쉬는 것이 보통이다.
                day = _weekday_on_or_after(day, r.choice([4, 4, 4, 4, 0, 0, 0, 2]))
                if day > TODAY or day in taken:
                    continue
                taken.add(day)
                if r.random() < 0.25:
                    take(p, day, r.choice(["am", "pm"]))
                    used_days[p["emp_no"]] = used_days.get(p["emp_no"], 0) + 0.5
                else:
                    take(p, day)
                    # 대부분 이틀 연속. 연달아 쉬면 「고립」이 아니다 —
                    # 그게 보통 사람의 연차 쓰는 모습이기도 하다.
                    if r.random() < 0.7 and day + timedelta(days=1) <= TODAY \
                            and (day + timedelta(days=1)).weekday() < 5:
                        taken.add(day + timedelta(days=1))
                        take(p, day + timedelta(days=1))
                        used_days[p["emp_no"]] = used_days.get(p["emp_no"], 0) + 1
                    used_days[p["emp_no"]] = used_days.get(p["emp_no"], 0) + 1
                break

    # ── 여름휴가 · 연휴 앞뒤 ────────────────────────────────
    # 여기가 없으면 사람들이 1년에 5일밖에 안 쓴 것이 되어, 「저사용」
    # 화면에 50명 중 35명이 뜬다. 그건 저사용이 아니라 그냥 데이터가
    # 모자란 것이다.
    #
    # 연속으로 3~5일 쉬는 덩어리를 넣는다. 연달아 쉬면 「고립」이 아니라
    # 이상패턴 점수는 그대로 두고 사용일수만 정상 범위로 올라간다.
    for p in people:
        for _blk in range(r.choice([1, 1, 2, 2, 2])):
            start = START + timedelta(days=r.randint(0, max(1, (TODAY - START).days - 7)))
            start = _weekday_on_or_after(start, 0)          # 월요일부터
            length = r.choice([3, 3, 4, 5])
            for k in range(length):
                day = start + timedelta(days=k)
                if day > TODAY or day.weekday() >= 5:
                    continue
                take(p, day)
                used_days[p["emp_no"]] = used_days.get(p["emp_no"], 0) + 1

    # ── 심어 두는 사람들 ────────────────────────────────────
    # 이름을 고정으로 고르지 않고 순번으로 고른다. 명단이 바뀌어도
    # 「몇 번째 사람」은 늘 있으므로 이 시나리오가 사라지지 않는다.
    def plant(idx: int, days: list[date], kind: str = "full"):
        p = people[idx % len(people)]
        for day in days:
            take(p, day, kind)
            used_days[p["emp_no"]] = used_days.get(p["emp_no"], 0) + (
                1 if kind == "full" else 0.5)
        return p

    # ① 위험 — 화·수·목 전일 연차 3번을 21일 안에.
    #    가중치 1.0 × 3 = 3.0, 고립 3회 → 「위험」 조건을 정확히 만족한다.
    base = TODAY - timedelta(days=40)
    tue = _weekday_on_or_after(base, 1)
    danger = plant(3, [tue, tue + timedelta(days=8), tue + timedelta(days=16)])

    # ② 검토 — 같은 모양이지만 한 번을 금요일로 바꾼다.
    #    금요일은 주말에 붙어 고립이 아니고 가중치도 낮다.
    base2 = TODAY - timedelta(days=95)
    wed = _weekday_on_or_after(base2, 2)
    review = plant(17, [wed, wed + timedelta(days=7), wed + timedelta(days=15)])

    # ③ 저사용 — 발생한 연차를 거의 안 쓴 사람.
    #    아래 발생내역에서 사용일수를 낮게 적는다.
    low = people[9 % len(people)]

    # ④ 급증 — 최근 두 달에 몰아 쓴 사람.
    spike_start = TODAY - timedelta(days=30)
    spike = plant(25, [_weekday_on_or_after(spike_start + timedelta(days=i * 3), 2)
                       for i in range(4)])

    # ── 발생내역 ────────────────────────────────────────────
    for p in people:
        hire = date.fromisoformat(p["hire_date"])
        years = (TODAY - hire).days // 365
        accrued = min(25, 15 + years // 2)
        used = round(used_days.get(p["emp_no"], 0), 1)
        if p["emp_no"] == low["emp_no"]:
            used = 1.0        # ★ 저사용으로 심는다
        accrual.append([
            # ★ 상태는 「발생됨」이어야 한다.
            #   앱은 이 값이 다르면 그 줄을 통째로 건너뛴다. 처음에 「재직」
            #   이라고 적었더니 저사용 화면이 늘 0명이었다. 오류도 경고도
            #   없고 그냥 비어 있어서, 데이터가 없는 건지 문제가 없는 건지
            #   구분이 안 됐다.
            p["emp_no"], p["name"], p["department"], "연차휴가", "발생됨",
            accrued, used, round(accrued - used, 1),
            f"{TODAY.year}-01-01", f"{TODAY.year}-12-31",
        ])

    holidays = [(f"{TODAY.year}-{m:02d}-{d:02d}", name)
                for name, (m, d) in COMPANY_HOLIDAYS]

    return {
        "usage": [USAGE_HEADER] + usage,
        "accrual": [ACCRUAL_HEADER] + accrual,
        "holidays": holidays,
        "planted": {"위험": danger["name"], "검토": review["name"],
                    "저사용": low["name"], "급증": spike["name"]},
    }
