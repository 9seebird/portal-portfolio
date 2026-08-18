# -*- coding: utf-8 -*-
"""AI 사용량 리포트 앱에 넣을 가짜 엑셀을 만든다.

이 앱은 사내 AI 게이트웨이가 뽑아 주는 **원본 로그(stat 시트)** 를 그대로
받아서 화면에서 집계한다. 그래서 만들 것도 원본 로그 한 장이면 된다.

    email  name  departmentFullName  type  toolName  model
    usageCount  inputToken  outputToken  inputCharge  outputCharge  date

리포트가 재미있어지려면 **한쪽으로 쏠려 있어야 한다.** 모두가 똑같이
쓰면 볼 것이 없다. 실제로도 늘 그렇지 않고, 몇 사람이 대부분을 쓴다.
그래서 상위 3명이 전체의 절반쯤을 쓰게 만들었다.

전부 지어낸 것이다.
"""

import random
from datetime import date, timedelta

import demo_company as C

# 화면에 뜨는 이름·값. 모델 단가는 100만 토큰당 원(₩) 기준으로 대충 잡았다.
MODELS = [
    ("gpt-5-mini", 350, 2800, 0.34),
    ("gpt-5-nano", 90, 700, 0.28),
    ("gemini-3.5-flash-lite", 140, 560, 0.22),
    ("claude-haiku-4.5", 400, 2000, 0.16),
]
TYPES = [("AGENT", 0.42), ("ASSISTANT", 0.33), ("WORKFLOW", 0.15),
         ("THIRDPARTY_APP", 0.06), ("ETC", 0.04)]
TOOLS = ["문서 요약", "번역", "메일 초안", "표 정리", "회의록 정리",
         "코드 리뷰", "이미지 읽기", "검색", "(없음)"]

HEADER = ["email", "name", "departmentFullName", "type", "toolName", "model",
          "usageCount", "inputToken", "outputToken", "inputCharge",
          "outputCharge", "date"]


def build(days: int = 60):
    r = random.Random(C.SEED + 3)
    people = [p for p in C.people() if p["status"] == "ACTIVE"]
    today = date.today()

    # 사람마다 「얼마나 열심히 쓰는가」를 미리 정한다.
    # 앞의 3명은 아주 많이, 뒤로 갈수록 적게. 실제 사용량 분포가 이렇다.
    heat = {}
    for i, p in enumerate(people):
        if i < 3:
            heat[p["emp_no"]] = r.uniform(6.0, 9.0)
        elif i < 12:
            heat[p["emp_no"]] = r.uniform(2.0, 4.0)
        elif i < 34:
            heat[p["emp_no"]] = r.uniform(0.5, 1.5)
        else:
            heat[p["emp_no"]] = r.uniform(0.0, 0.4)   # 거의 안 쓰는 사람들

    rows = [HEADER]
    for d in range(days):
        day = today - timedelta(days=days - 1 - d)
        if day.weekday() >= 5:            # 주말은 확 준다
            if r.random() < 0.8:
                continue
        for p in people:
            n = r.random() * heat[p["emp_no"]] * 3
            for _ in range(int(n)):
                model, in_price, out_price, _w = r.choices(
                    MODELS, [m[3] for m in MODELS])[0]
                kind = r.choices([t[0] for t in TYPES], [t[1] for t in TYPES])[0]
                calls = r.randint(1, 4)
                in_tok = r.randint(600, 9000) * calls
                out_tok = r.randint(120, 1800) * calls
                rows.append([
                    p["email"], "", p["department"], kind,
                    r.choice(TOOLS), model, calls, in_tok, out_tok,
                    round(in_tok * in_price / 1_000_000, 2),
                    round(out_tok * out_price / 1_000_000, 2),
                    day.isoformat(),
                ])
    return rows


def name_map() -> dict[str, str]:
    """이메일 → 이름.

    로그에는 이메일만 있고 이름이 없다 (게이트웨이가 이름을 모른다).
    그래서 화면이 따로 들고 있는 표다. 이게 없으면 사용자별 순위가
    전부 이메일로 나와서 누가 누군지 알 수 없다.
    """
    return {p["email"]: p["name"] for p in C.people()}
