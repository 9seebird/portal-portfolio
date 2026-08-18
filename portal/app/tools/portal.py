"""포털 앱 안내 도구.

"그거 어디서 봐?" 같은 질문에 해당 앱과 바로가기를 안내한다.
권한이 없는 앱은 목록에 포함되지 않으므로 존재 자체가 노출되지 않는다.

### 주소를 모델에게 주지 않는 이유

앱 목록을 돌려줄 때 url 을 함께 담으면 모델이 답변 본문에
"IT 매뉴얼 (/manual/)" 처럼 경로를 적는다. 대부분의 직원은 그 경로로
무엇을 해야 하는지 모르고, 오히려 답이 잘못 나온 것처럼 보인다.

이동은 화면이 담당한다. 앱이 하나로 특정될 때만 detail_url 을 주고,
그게 **바로가기 버튼**으로 그려진다. 여러 개일 때는 이름만 말하고
사용자가 더 좁혀 물으면 그때 버튼이 나간다.

프롬프트로 "경로를 쓰지 마"라고만 해두면 지킬 때도 있고 안 지킬 때도 있다.
아예 주지 않는 편이 확실하다.
"""

import re

from .. import access, services
from ..registry import User, tool
from ..schemas import ToolResult, ok


@tool(
    name="find_app",
    label="사내 앱 검색",
    description=(
        "사내 포털에서 원하는 업무를 처리할 수 있는 앱을 찾아 안내한다. "
        "'어디서 봐?', '어디서 신청해?', '무슨 메뉴야?', '그거 어느 시스템이야?', "
        "'무슨 앱 쓸 수 있어?' 같이 위치를 묻거나 "
        "특정 데이터를 조회하는 도구가 따로 없는 업무를 요청할 때 사용한다. "
        "조회 결과 자체가 필요한 경우에는 해당 조회 도구를 우선 사용한다."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "찾으려는 업무나 주제. 예: 자산, 매뉴얼, 비용처리, 점검",
            }
        },
    },
)
def find_app(user: User, keyword: str | None = None) -> ToolResult:
    apps = access.visible(user, services.all_services(include_disabled=False), user.ip)

    if not apps:
        # data 를 비워 둔다. 빈 목록을 넘기면 모델이 "(apps: [])" 처럼
        # 그대로 옮겨 적는 일이 생긴다. 없다는 말은 summary 한 줄이면 된다.
        return ok(summary="접근 가능한 앱이 없습니다. IT 담당자에게 문의하세요.",
                  data={"작성지침": "이 문장에서 끝내십시오. 권한 요청을 대신 써 주겠다고 "
                                "먼저 제안하지 말고, **없는 화면이나 창구를 지어내지 "
                                "마십시오.** '고객지원 화면', '문의 게시판' 같은 것은 "
                                "이 회사에 없습니다."})

    names = ", ".join(a["name"] for a in apps)

    if not keyword:
        return ok(
            summary=f"현재 사용 가능한 앱은 {names} 입니다.",
            data={"앱": [{"이름": a["name"], "설명": a["description"]} for a in apps]},
        )

    # "AI 비용" 처럼 두 단어로 물으면 통째로 부분일치를 보는 방식으로는
    # 아무것도 안 걸린다. 낱말로 쪼개서 본다.
    kw = keyword.strip().lower()
    words = [w for w in re.split(r"[\s,]+", kw) if len(w) >= 2] or [kw]

    def score(a: dict) -> int:
        """어디에서 걸렸는지에 따라 무게가 다르다.

        예전에는 어디서 걸리든 1점이었다. 그래서 "AI 매뉴얼" 을 물으면
        'AI' 하나가 걸린 **AI 리포트**와 '매뉴얼'이 걸린 **IT 매뉴얼**이
        같은 점수가 되고, 먼저 등록된 쪽이 답으로 나갔다.
        사람은 '매뉴얼'을 찾은 것인데 리포트로 보내진다.

        이름에 든 낱말이 가장 정확하다. 설명에 스치듯 나온 것은 약하다.
        """
        name = (a["name"] or "").lower()
        keys = (a["keywords"] or "").lower()
        desc = (a["description"] or "").lower()
        pts = 0
        hit = 0
        for w in words:
            if w in name:
                pts += 5; hit += 1
            elif w in keys:
                pts += 3; hit += 1
            elif w in desc:
                pts += 1; hit += 1
        if not hit:
            return 0
        # 물어본 낱말이 다 걸린 쪽을 크게 앞세운다
        if hit == len(words):
            pts += 4
        # 물어본 말이 통째로 이름에 들어 있으면 확실하다
        if kw in name:
            pts += 6
        # 우리말은 뒤에 오는 말이 알맹이다 — "AI 매뉴얼" 은 매뉴얼을 찾는 것이지
        # AI 를 찾는 것이 아니다. 마지막 낱말이 이름에 걸리면 그쪽을 앞세운다.
        if len(words) > 1 and words[-1] in name:
            pts += 3
        return pts

    scored = [(score(a), a) for a in apps]
    best = max((s for s, _ in scored), default=0)
    matched = [a for s, a in scored if s == best] if best else []

    # ── 권한이 없어서 안 보이는 앱이 더 잘 맞는 경우 ──────────────
    # 이게 없으면 "IT 매뉴얼 있어?" 에 엉뚱한 앱을 대준다. 앱이 있는데
    # 권한이 없는 것과, 그런 앱이 아예 없는 것은 완전히 다른 상황이다.
    hidden = [a for a in services.all_services(include_disabled=False)
              if a["id"] not in {x["id"] for x in apps}]
    h_scored = [(score(a), a) for a in hidden]
    h_best = max((s for s, _ in h_scored), default=0)
    if h_best > best:
        names_h = ", ".join(a["name"] for s, a in h_scored if s == h_best)
        return ok(
            summary=f"'{keyword}' 은(는) {names_h} 에 있습니다. "
                    "다만 지금 계정에는 그 앱을 볼 권한이 없습니다. "
                    "IT 담당자에게 권한을 요청해 주세요.",
            data={"앱": names_h, "권한": "없음",
                  "작성지침": "다른 앱을 대신 안내하지 마십시오. "
                          "권한이 없다는 사실만 전하십시오."},
        )

    # 정확히 하나 — 바로 안내
    if len(matched) == 1:
        a = matched[0]
        return ok(
            summary=f"{a['name']} 에서 확인하실 수 있습니다. {a['description']}",
            data={"앱": a["name"], "설명": a["description"]},
            detail_url=a["url"],
        )

    # 여러 개 — 후보 제시
    if matched:
        cand = ", ".join(a["name"] for a in matched)
        return ok(
            summary=f"'{keyword}' 관련 앱은 {cand} 입니다.",
            data={"앱": [{"이름": a["name"], "설명": a["description"]} for a in matched],
                  "작성지침": "어느 것을 찾으시는지 물어보고, 앱 이름만 알려주십시오."},
        )

    # 못 찾음 — 있는 것처럼 말하지 않도록 결과에 명시한다.
    # 접근 권한이 없는 앱도 여기로 온다. "권한이 없다"고 알리면
    # 그 앱의 존재를 알려주는 셈이므로 구분하지 않는다.
    return ok(
        # summary 는 **사용자가 읽을 문장**이다. 모델에게 시킬 말을 여기 섞으면
        # 그 문장이 그대로 화면에 나온다. 지시는 작성지침으로 따로 준다.
        summary=(f"'{keyword}' 에 해당하는 앱을 찾지 못했습니다. "
                 f"현재 사용 가능한 앱은 {names} 입니다."),
        data={
            "찾은 앱": "없음",
            "찾던 말": keyword,
            "쓸 수 있는 앱": [{"이름": a["name"], "설명": a["description"]} for a in apps],
            "작성지침": "찾으시는 앱이 목록에 없다면 접근 권한이 없거나 아직 등록되지 "
                    "않은 것이므로, IT 담당자에게 문의하도록 안내하십시오. "
                    "목록에 있는 앱이 요청한 기능을 제공한다고 추측해서 답하지 마십시오. "
                    "앱 이름만 알려주고 주소나 경로는 적지 마십시오.",
        },
    )
