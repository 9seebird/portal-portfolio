"""매뉴얼 · 운영 체크리스트 연결 도구.

### 왜 이걸 붙이나 — 인수인계

지금 사내 지식은 이렇게 흩어져 있다.

    매뉴얼 11개 · 설명 239줄 · 화면 캡처 181장
    운영 체크리스트 59항목 (수시·매일·월간·분기·연간)

인수받는 사람은 **무엇을 봐야 하는지조차 모른다.** 11개를 하나씩 열어
보는 수밖에 없다. "SAP 신규 엔트리 추가는 어디 나와 있지?" 를 찾는 데
드는 시간이 실제 작업 시간보다 길다.

챗이 그 자리를 짚어 주면 그 시간이 사라진다.

    "SAP 신규 엔트리 추가 어떻게 해?"
      → SAP GUI 매뉴얼 · Menu 2 · 그 단계 글자 그대로 + 바로가기

### 글자만 준다

매뉴얼의 알맹이는 화면 캡처인 경우가 많다 (SAP 보고서 매뉴얼은 41장).
챗은 글자만 전할 수 있다. 그래서 **어느 매뉴얼 몇 번 항목인지**를
분명히 알려주고 화면으로 보낸다. 그것만으로도 찾는 시간이 사라진다.

### 앱을 고치지 않았다

이 앱은 백엔드가 없다. nginx 가 정적 파일을 줄 뿐이다.
그래서 포털이 **HTTP 로 그 파일을 가져와** 읽는다. 파일 시스템을
공유하지 않는다 — 앱이 어디에 있든, 나중에 다른 서버로 옮겨도 그대로 돈다.

읽는 것은 두 곳이다.

    /manuals/data/manuals.js     window.MANUAL_DATA = { ... }
    /checklist/index.html        <script id="app-data"> { ... } </script>

두 번째는 화면 파일 안에 데이터가 박혀 있어서 뽑아내야 한다.
앱을 고쳐서 JSON 을 따로 빼면 깔끔하겠지만, 그러면 **편집 모드가
만들어 내는 파일 모양이 달라진다.** 지금 담당자가 쓰는 방법을
바꾸지 않는 편이 낫다고 보았다.

### 자주 바뀌지 않는다

매뉴얼과 체크리스트는 한 달에 몇 번 고칠까 말까다. 매번 받아오면
17MB 짜리 앱에 쓸데없이 요청이 간다. 몇 분 동안 담아 둔다.
"""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from ..registry import User, tool
from ..schemas import ToolResult, fail

# ── 환경에 맞게 수정할 부분 ──────────────────────────────────
API = os.environ.get("GUIDE_API", "http://demo-guide-web:80").rstrip("/")

# 직원이 눌러서 들어갈 주소. 프록시 경로와 맞춘다.
MANUAL_URL = os.environ.get("MANUAL_URL", "/manual/")
CHECKLIST_URL = os.environ.get("CHECKLIST_URL", "/checklist/")

TIMEOUT = float(os.environ.get("GUIDE_TIMEOUT", "5"))

# 담아 두는 시간(초). 매뉴얼은 한 달에 몇 번 바뀔까 말까다.
CACHE_SEC = int(os.environ.get("GUIDE_CACHE_SEC", "300"))
# ────────────────────────────────────────────────────────────

_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()


# ── 찾을 낱말 고르기 ─────────────────────────────────────────
#
# 예전에는 물어본 문장을 띄어쓰기로만 잘라서 그대로 다 찾았다. 그래서
# "사내앱 규칙 중 내가 신경써야 하는 부분" 을 물으면 조사 '중', 어미 '하는',
# 의존명사 '부분' 이 매뉴얼 아무 데나 스쳤고, 정작 '사내앱'·'신경써야' 는
# 0건인데도 SAP 매뉴얼이 1등으로 올라왔다. "점심 메뉴 추천해줘" 로는
# '메뉴' 한 글자가 걸려 SAP 매뉴얼 12곳이 나왔다.
#
# 한 글자는 버리고, 뜻이 없는 말도 버린다. portal.py 의 find_app 이
# 이미 `len(w) >= 2` 로 같은 일을 하고 있다. 여기만 빠져 있었다.
_STOP = {
    "하는", "되는", "있는", "없는", "같은", "그런", "이런", "저런", "관한",
    "알려줘", "알려", "보여줘", "보여", "찾아줘", "찾아", "해줘", "하고", "해서",
    "어떻게", "무엇", "뭐가", "뭔가", "뭐야", "어디", "언제", "누가", "얼마나",
    "부분", "내용", "방법", "경우", "때문", "관련", "대해", "대한", "위해", "위한",
    "전체", "그리고", "그거", "저거", "이거", "우리", "제가", "내가", "나는",
    "합니다", "입니다", "인가요", "인가", "일까", "일까요", "건가요", "인지",
    "좀더", "다시", "지금", "혹시", "정말", "진짜",
    "나와", "있어", "없어", "있나", "없나", "되나", "하나", "무슨", "어떤",
    "어디에", "그럼", "해도", "되죠", "하죠", "인데", "라면",
    "알려줄래", "알려주라", "궁금해", "뭐뭐", "있을까", "좋을까", "할까",
}

# 동사·형용사가 이어지는 어미로 끝나면 찾을 낱말이 아니다.
# "열어도", "신경써야", "확인하면" 같은 것들. 이런 말이 하나 섞였다고
# "물어본 낱말 중 절반밖에 못 찾았다" 로 세면 멀쩡한 검색이 막힌다.
_ENDING = re.compile(r"(어도|아도|으면|하면|되면|는데|지만|니까|려고|하게|되게)$")
# 이런 소리로 끝나면 대개 동사다 — "나눠", "보여줘", "확인해봐".
# 이름씨(명사)가 이렇게 끝나는 일은 드물어서 두 글자부터 적용한다.
_VERB2 = re.compile(r"(눠|줘|둬|봐|켜|져|쳐|워)$")
# '야'·'와' 는 "분야"·"조와" 처럼 이름씨에도 나온다. 세 글자부터만 본다.
_VERB3 = re.compile(r"(야|와)$")


def _words(q: str) -> list[str]:
    """물어본 문장에서 실제로 찾을 낱말만 남긴다."""
    raw = [w.strip(" .,?!\"'`~()[]{}<>:;·/").lower()
           for w in re.split(r"[\s,·/]+", q or "")]
    keep = [w for w in raw
            if len(w) >= 2 and w not in _STOP
            and not _ENDING.search(w)
            and not _VERB2.search(w)
            and not (len(w) >= 3 and _VERB3.search(w))]
    if keep:
        return keep
    # 전부 걸러졌으면 한 글자라도 남긴다 (예: "IP")
    return [w for w in raw if w] or [(q or "").strip()]


def _need(words: list[str]) -> int:
    """몇 개는 걸려야 '찾았다' 고 할 수 있나.

    낱말이 둘이면 둘 다 걸려야 한다. "점심 메뉴" 에서 '메뉴' 하나만
    스친 것을 찾았다고 하면 안 된다. 셋 이상이면 과반.
    """
    n = len(words)
    if n <= 1:
        return 1
    return max(2, (n + 1) // 2)


# 우리말은 낱말 뒤에 조사·어미가 붙는다. "MCP가", "제출할", "포트를" 은
# 매뉴얼 글자와 그대로는 안 맞는다. 뒤를 조금씩 떼어 보고 맞춰 본다.
_TAILS = ("으로", "에서", "에게", "까지", "부터", "이라고", "라고", "이나",
          "에는", "에도", "이란", "합니다", "해야", "하는", "한다", "했다",
          "은", "는", "이", "가", "을", "를", "의", "에", "도", "만",
          "과", "와", "로", "야", "랑", "할", "해", "함", "된", "됨")


def _variants(w: str) -> list[str]:
    """낱말 하나에서 찾아볼 꼴들. 원래 낱말과 조사를 뗀 꼴."""
    out = [w]
    for t in _TAILS:
        if w.endswith(t) and len(w) - len(t) >= 2:
            stem = w[: -len(t)]
            if stem not in out:
                out.append(stem)
    return out


def _hit(w: str, text: str) -> bool:
    """낱말이 글 안에 있나. 대소문자와 띄어쓰기 차이는 무시한다."""
    low = text.lower()
    flat = low.replace(" ", "")
    for v in _variants(w):
        if v in low or v.replace(" ", "") in flat:
            return True
    return False


def _fetch(path: str) -> str:
    """앱에서 파일을 받아온다. 잠깐 담아 둔다."""
    now = time.time()
    with _lock:
        hit = _cache.get(path)
        if hit and now - hit[0] < CACHE_SEC:
            return hit[1]           # type: ignore[return-value]

    req = urllib.request.Request(API + path, headers={"Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        text = r.read().decode("utf-8", "replace")

    with _lock:
        _cache[path] = (now, text)
    return text


def _down(e: Exception, what: str) -> ToolResult:
    if isinstance(e, urllib.error.URLError):
        return fail(f"{what} 서비스에 연결하지 못했습니다. ({API}) — {e.reason}")
    return fail(f"{what}을(를) 읽지 못했습니다. {type(e).__name__}")


# ── 매뉴얼 ───────────────────────────────────────────────────
def _manuals() -> list[dict]:
    """manuals.js 는 자바스크립트다. 앞의 `window.MANUAL_DATA =` 를 떼면 JSON."""
    raw = _fetch("/manuals/data/manuals.js")
    i = raw.index("{")
    d = json.loads(raw[i:].rstrip().rstrip(";"))
    return d.get("manuals", [])


def _steps(sec: dict) -> list[str]:
    out = []
    for b in sec.get("blocks", []):
        out.extend(s for s in b.get("steps", []) if str(s).strip())
    return out


def _images(sec: dict) -> int:
    return sum(len(b.get("images", [])) for b in sec.get("blocks", []))


def _manual_link(m: dict, sec_idx: int | None = None) -> str:
    """찾은 그 항목으로 바로 가는 주소.

    매뉴얼 화면은 `#manual/<매뉴얼id>/<항목번호>` 로 열린다. 앱이 원래
    목차 링크에 쓰던 모양 그대로다. 경로가 아니라 # 인 것은 이 앱이
    정적 파일이라 `/manual/sap-gui` 같은 경로는 404 가 되기 때문이다.
    """
    mid = str(m.get("id") or "").strip()
    if not mid:
        return MANUAL_URL
    frag = f"#manual/{urllib.parse.quote(mid, safe='')}"
    if sec_idx is not None:
        frag += f"/{int(sec_idx)}"
    return MANUAL_URL + frag


@tool(
    name="search_manual",
    label="IT 매뉴얼 검색",
    description=(
        "사내 IT 매뉴얼에서 필요한 대목을 찾아 준다. "
        "'SAP 신규 엔트리 어떻게 추가해?', 'NAS 백업 설정 어디 나와 있어?', "
        "'그룹웨어 계정 만드는 법', '카스퍼스키 설치 매뉴얼 있어?' 처럼 "
        "**업무 절차나 사용법**을 물을 때 쓴다. "
        "SAP GUI·SAP 분기보고서·NAS·상해 ITO·Unipost·한비로 그룹웨어·"
        "웍스AI·Grafana·카스퍼스키·M365 매뉴얼이 들어 있다. "
        "찾은 절차의 글자를 그대로 돌려주며, 화면 캡처는 매뉴얼 화면에서 봐야 한다. "
        "※ 위에 적힌 매뉴얼 안에서만 찾는다. 그 밖의 주제는 여기에 없다. "
        "사내앱을 만들 때 지키는 표준 규칙(포트·권한·저장·제출물)이면 "
        "search_app_rules, AI 용어나 프롬프트 예시면 search_ai_ref, "
        "주기별 운영 업무면 get_checklist, 어느 앱에서 하는 일인지면 find_app 을 쓴다."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string",
                      "description": "찾을 말. 'SAP 엔트리', '백업', '계정 생성' 처럼"},
        },
        "required": ["query"],
    },
    service="manual",
)
def search_manual(user: User, query: str) -> ToolResult:
    try:
        manuals = _manuals()
    except Exception as e:  # noqa: BLE001
        return _down(e, "IT 매뉴얼")

    q = (query or "").strip()
    if not q:
        return fail("무엇을 찾을지 알려주세요.")
    # 띄어쓰기가 달라도 걸리게 한다 ("신규 엔트리" / "신규엔트리")
    words = _words(q)
    need = _need(words)

    # 어디에서 걸렸는지에 따라 무게를 다르게 준다.
    # "SAP 신규 엔트리" 를 찾을 때 'SAP' 하나만 걸린 항목이 28개나 나오면
    # 맞는 답이 그 속에 묻힌다. 항목 이름에서 걸린 것이 가장 정확하다.
    hits = []
    for m in manuals:
        for idx, sec in enumerate(m.get("sections", [])):
            steps = _steps(sec)
            sec_title = sec.get("title", "")
            body = " ".join(steps)
            man_title = m.get("title", "")
            score = 0
            matched = 0
            for w in words:
                if _hit(w, sec_title):
                    score += 3; matched += 1
                elif _hit(w, body):
                    score += 2; matched += 1
                elif _hit(w, man_title):
                    score += 1; matched += 1
            # 물어본 낱말의 과반은 걸려야 한다.
            # 하나만 스친 것을 "찾았다" 고 하면 엉뚱한 답이 나간다.
            if matched < need:
                continue
            # 여러 낱말로 물었으면 다 걸린 쪽을 크게 앞세운다
            score += matched * 2
            hits.append((score, m, sec, steps, idx))

    # 아래 상대 컷(best * 0.6)만으로는 막지 못한다. 1등 자체가 형편없으면
    # 그 0.6 도 같이 내려가기 때문이다. 절대 바닥을 따로 둔다.
    #   본문에 한 낱말만 걸린 경우가 2 + 2 = 4 점이다. 그 아래는 우연이다.
    if hits and max(h[0] for h in hits) < 4:
        hits = []

    if not hits:
        titles = ", ".join(m.get("title", "") for m in manuals)
        return ToolResult(
            summary=f"IT 매뉴얼에는 '{q}' 에 해당하는 대목이 없습니다.",
            data={"결과": "없음", "있는 매뉴얼": titles,
                  "작성지침": "**없다고 그대로 말하십시오.** 비슷해 보이는 다른 매뉴얼을 "
                          "끌어다 답하지 마십시오. 물어본 것이 사내앱을 만들 때 "
                          "지키는 규칙이면 search_app_rules, AI 용어나 프롬프트면 "
                          "search_ai_ref, 어느 앱에서 하는 일인지면 find_app 을 "
                          "대신 부르십시오."},
            detail_url=MANUAL_URL)

    hits.sort(key=lambda x: -x[0])
    # 가장 잘 맞는 것과 견줘 한참 떨어지는 것은 "찾은 곳"으로 세지 않는다.
    # 세어 봐야 "외 27곳" 처럼 겁만 주고 쓸모가 없다.
    best = hits[0][0]
    hits = [h for h in hits if h[0] >= best * 0.6]
    top = hits[:4]

    items = []
    for _, m, sec, steps, _idx in top:
        items.append({
            "매뉴얼": m.get("title"),
            "항목": sec.get("title"),
            "절차": steps[:8],
            "화면 캡처": f"{_images(sec)}장 (매뉴얼 화면에서 볼 수 있습니다)"
                      if _images(sec) else "없음",
        })

    first = top[0]
    return ToolResult(
        summary=(f"{first[1].get('title')} — {first[2].get('title')}"
                 + (f" 외 {len(hits) - 1}곳" if len(hits) > 1 else "")),
        data={"찾은 곳": items,
              "작성지침": "절차 글자는 그대로 알려주십시오. 화면 캡처가 있는 항목은 "
                      "'자세한 화면은 매뉴얼에서 보시면 됩니다' 라고 덧붙이십시오."},
        # 그 매뉴얼의 그 항목으로 바로 보낸다. 목록에서 다시 찾게 하지 않는다.
        detail_url=_manual_link(first[1], first[4]),
        truncated=len(hits) > len(top),
    )


@tool(
    name="list_manuals",
    label="IT 매뉴얼 목록",
    description=(
        "사내에 어떤 IT 매뉴얼이 있는지 목록으로 알려준다. "
        "'무슨 매뉴얼 있어?', '매뉴얼 뭐뭐 있는지 알려줘', "
        "'인수인계 자료 뭐가 있어' 처럼 **무엇이 있는지**를 물을 때 쓴다. "
        "특정 절차를 찾는 것이면 search_manual 을 쓴다."
    ),
    input_schema={"type": "object", "properties": {}},
    service="manual",
)
def list_manuals(user: User) -> ToolResult:
    try:
        manuals = _manuals()
    except Exception as e:  # noqa: BLE001
        return _down(e, "IT 매뉴얼")

    items = []
    for m in manuals:
        secs = m.get("sections", [])
        items.append({"매뉴얼": m.get("title"),
                      "항목 수": len(secs),
                      "항목": [s.get("title") for s in secs[:6]]})
    return ToolResult(
        summary=f"매뉴얼 {len(manuals)}개가 있습니다.",
        data={"매뉴얼": items},
        detail_url=MANUAL_URL,
    )


# ── 사내앱 규칙 · AI 참고자료 ────────────────────────────────
#
# 둘 다 백엔드가 없는 정적 화면이다. 매뉴얼과 같은 방식으로 HTTP 로
# 자료를 가져온다. 다만 화면(HTML)을 긁지 않고 **옆에 둔 data.json 을
# 읽는다.** 화면 모양을 바꿔도 챗이 깨지지 않게 하려는 것이다.
RULES_URL = os.environ.get("RULES_URL", "/rules/")
AIREF_URL = os.environ.get("AIREF_URL", "/ai-ref/")


def _rules() -> dict:
    return json.loads(_fetch("/rules/data.json"))


def _airef() -> dict:
    return json.loads(_fetch("/ai-ref/data.json"))


def _pick(rows: list[dict], fields: tuple[str, ...], words: list[str],
          need: int, weights: tuple[int, ...]) -> list[tuple[int, dict]]:
    """낱말이 어디에서 걸렸는지에 따라 점수를 주고, 과반을 못 채우면 버린다."""
    out = []
    for r in rows:
        score = 0
        matched = 0
        for w in words:
            for f, wt in zip(fields, weights):
                if _hit(w, str(r.get(f, ""))):
                    score += wt
                    matched += 1
                    break
        if matched < need:
            continue
        out.append((score + matched * 2, r))
    out.sort(key=lambda x: -x[0])
    return out


@tool(
    name="search_app_rules",
    label="사내앱 규칙 검색",
    description=(
        "사내에서 쓸 웹 프로그램(사내앱)을 만들 때 지켜야 하는 회사 표준 규칙을 찾아 준다. "
        "'사내앱 규칙 알려줘', '내가 신경 써야 할 게 뭐야', '포트 열어도 돼?', "
        "'권한은 어떻게 나눠?', '어떤 파일을 제출해?', '데이터는 어디에 저장해?', "
        "'왜 반려됐어?', '표준규칙이 뭐야', '바이브코딩으로 만들 때 뭐 지켜야 해' 처럼 "
        "**앱을 만들고 제출하는 규칙**을 물을 때 쓴다. "
        "규칙은 열 묶음으로 나뉘어 있고, 대부분은 프롬프트 생성기가 자동으로 넣어 주는 것이며 "
        "사람이 직접 챙겨야 하는 것은 아홉 가지뿐이다. "
        "낱말을 비우고 부르면 그 아홉 가지를 돌려준다. "
        "※ 시스템 사용법(SAP·NAS·그룹웨어)은 search_manual, "
        "IT 담당자의 주기별 운영 업무는 get_checklist, "
        "AI 용어나 프롬프트 예시는 search_ai_ref 를 쓴다."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string",
                      "description": "찾을 말. '포트', '권한', '제출', '저장' 처럼. "
                                     "비우면 사람이 챙겨야 하는 규칙만 돌려준다"},
        },
    },
    service="rules",
)
def search_app_rules(user: User, query: str | None = None) -> ToolResult:
    try:
        d = _rules()
    except Exception as e:  # noqa: BLE001
        return _down(e, "사내앱 규칙")

    rules = d.get("rules", [])
    ver = d.get("version", "")
    q = (query or "").strip()

    # 무엇을 찾을지 안 밝혔으면 "사람이 챙길 것" 만 준다.
    # 규칙 전체를 늘어놓으면 읽지 않는다.
    if not q:
        mine = [r for r in rules if r.get("who") == "내가 챙길 것"]
        return ToolResult(
            summary=f"규칙은 모두 {len(rules)}가지인데, 사람이 직접 챙길 것은 "
                    f"{len(mine)}가지입니다. 나머지는 프롬프트 생성기가 넣어 줍니다.",
            data={"규칙 버전": ver,
                  "내가 챙길 것": [{"묶음": r["group"], "규칙": r["title"],
                                "왜": r["why"]} for r in mine],
                  "작성지침": "이 아홉 가지를 그대로 알려 주십시오. 나머지 규칙은 "
                          "생성기가 자동으로 넣어 주므로 외울 필요가 없다는 점을 "
                          "꼭 덧붙이십시오."},
            detail_url=RULES_URL)

    words = _words(q)
    hits = _pick(rules, ("title", "why", "group"), words, _need(words), (3, 2, 2))
    if not hits or hits[0][0] < 4:
        # 이 도구를 불렀다는 것은 규칙을 알고 싶다는 뜻이다. 딱 맞는 것을
        # 못 찾았다고 빈손으로 돌려보내면, 정작 이 사람이 알아야 할
        # 아홉 가지도 못 보고 끝난다. 그것만 대신 보여 준다.
        mine = [r for r in rules if r.get("who") == "내가 챙길 것"]
        return ToolResult(
            summary=f"사내앱 규칙에는 '{q}' 에 해당하는 것이 없습니다. "
                    f"(사람이 직접 챙길 것은 모두 {len(mine)}가지입니다)",
            data={"규칙 버전": ver,
                  "찾은 결과": "없음",
                  "대신 보여드리는 것 — 내가 챙길 것":
                      [{"묶음": r["group"], "규칙": r["title"], "왜": r["why"]}
                       for r in mine],
                  "작성지침": "물어보신 말로는 딱 맞는 규칙을 못 찾았다고 먼저 밝히고, "
                          "대신 사람이 챙겨야 하는 것들을 알려 주십시오. "
                          "없는 규칙을 지어내지 마십시오."},
            detail_url=RULES_URL)

    top = hits[:6]
    return ToolResult(
        summary=(f"{top[0][1]['title']}"
                 + (f" 외 {len(hits) - 1}가지" if len(hits) > 1 else "")),
        data={"규칙 버전": ver,
              "찾은 규칙": [{"묶음": r["group"], "규칙": r["title"], "왜": r["why"],
                         "누가": r["who"]} for _, r in top],
              "작성지침": "규칙 문장을 그대로 알려 주십시오. '누가' 가 "
                      "'생성기가 넣어줌' 이면 사람이 신경 쓸 필요가 없다는 뜻이므로 "
                      "그 점을 덧붙이십시오."},
        detail_url=RULES_URL,
        truncated=len(hits) > len(top),
    )


@tool(
    name="search_ai_ref",
    label="AI 용어 · 프롬프트 찾기",
    description=(
        "AI 용어 풀이와 바로 복사해 쓰는 프롬프트 예시를 찾아 준다. "
        "'MCP 가 뭐야', '할루시네이션이 무슨 뜻이야', '토큰이 뭐야', "
        "'회의록 정리하는 프롬프트 있어?', '엑셀 정리 프롬프트 알려줘', "
        "'프롬프트 잘 쓰는 법', '바이브코딩이 뭐야' 처럼 "
        "**모르는 AI 용어를 묻거나, 쓸 만한 프롬프트를 찾을 때** 쓴다. "
        "용어 192개, 그대로 복사해 쓰는 프롬프트 216개, 바이브코딩 입문 70항목이 들어 있다. "
        "※ 사내앱을 만드는 표준 규칙은 search_app_rules, "
        "시스템 사용법은 search_manual 을 쓴다."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string",
                      "description": "찾을 말. 'MCP', '회의록', '할루시네이션' 처럼"},
        },
        "required": ["query"],
    },
    service="ai-ref",
)
def search_ai_ref(user: User, query: str) -> ToolResult:
    try:
        d = _airef()
    except Exception as e:  # noqa: BLE001
        return _down(e, "AI 참고자료")

    q = (query or "").strip()
    if not q:
        return fail("무엇을 찾을지 알려주세요.")

    items = d.get("items", [])
    words = _words(q)
    hits = _pick(items, ("title", "short", "text"), words, _need(words), (3, 2, 1))
    if not hits or hits[0][0] < 4:
        return ToolResult(
            summary=f"참고자료에는 '{q}' 에 해당하는 것이 없습니다.",
            data={"결과": "없음",
                  "들어 있는 것": "AI 용어집 · AI 프롬프트집 · 바이브코딩 입문",
                  "작성지침": "**없다고 그대로 말하십시오.** 비슷해 보이는 다른 항목을 "
                          "끌어다 답하지 마십시오."},
            detail_url=AIREF_URL)

    top = hits[:5]
    return ToolResult(
        summary=(f"{top[0][1]['title']} ({top[0][1]['tab']})"
                 + (f" 외 {len(hits) - 1}건" if len(hits) > 1 else "")),
        data={"찾은 것": [{"어디": r["tab"], "제목": r["title"],
                       "한 줄": r["short"], "설명": r["text"]} for _, r in top],
              "작성지침": "설명을 쉬운 말로 풀어 주십시오. 프롬프트집에서 나온 것이면 "
                      "그 문장을 그대로 복사해 쓸 수 있다고 알려 주십시오."},
        detail_url=AIREF_URL,
        truncated=len(hits) > len(top),
    )


# ── 운영 체크리스트 ──────────────────────────────────────────
PERIODS = {"adhoc": "수시", "daily": "매일", "monthly": "월간",
           "quarterly": "분기", "yearly": "연간"}
# 사람이 말하는 대로 받는다
PERIOD_WORDS = {
    "수시": "adhoc", "아무때나": "adhoc", "adhoc": "adhoc",
    "매일": "daily", "일간": "daily", "하루": "daily", "daily": "daily",
    "월간": "monthly", "매월": "monthly", "달마다": "monthly", "한달": "monthly",
    "monthly": "monthly",
    "분기": "quarterly", "quarterly": "quarterly",
    "연간": "yearly", "매년": "yearly", "일년": "yearly", "년간": "yearly",
    "yearly": "yearly",
}

# 체크리스트는 화면 파일 안에 데이터가 박혀 있다.
# 이 <script id="app-data"> 가 앱과의 약속이다. 앱을 고칠 때 이 id 를
# 바꾸면 여기도 같이 고쳐야 한다.
_APPDATA_RE = re.compile(
    r'<script[^>]*id=["\']app-data["\'][^>]*>(.*?)</script>', re.S)


def _checklist() -> dict:
    raw = _fetch("/checklist/index.html")
    m = _APPDATA_RE.search(raw)
    if not m:
        raise ValueError("체크리스트 화면에서 자료를 찾지 못했습니다 (app-data)")
    return json.loads(m.group(1))


@tool(
    name="get_checklist",
    label="IT 운영 체크리스트 조회",
    description=(
        "IT 운영·유지보수 체크리스트를 알려준다. "
        "'월간에 뭐 해야 해?', '분기 업무 알려줘', '매일 뭐 확인해?', "
        "'연간 업무 뭐 있어', '인수인계 받았는데 뭐부터 해야 해' 처럼 "
        "**주기별로 할 일**을 물을 때 쓴다. "
        "수시·매일·월간·분기·연간으로 나뉘어 있다. "
        "유지보수 업체 연락처도 함께 들어 있다. "
        "※ 이것은 IT 담당자의 운영 업무 목록이다. 사내앱을 만들 때 지키는 "
        "개발 규칙이면 search_app_rules, 시스템 사용법이면 search_manual 을 쓴다."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "period": {"type": "string",
                       "description": "주기. 수시·매일·월간·분기·연간 중 하나. "
                                      "비우면 전부"},
            "vendors": {"type": "boolean",
                        "description": "유지보수 업체 정보를 볼 때 true"},
        },
    },
    service="checklist",
)
def get_checklist(user: User, period: str | None = None,
                  vendors: bool = False) -> ToolResult:
    try:
        d = _checklist()
    except Exception as e:  # noqa: BLE001
        return _down(e, "운영 체크리스트")

    if vendors:
        vs = d.get("vendors", [])
        if not vs:
            return ToolResult(summary="등록된 유지보수 업체가 없습니다.",
                              data={"업체": []},
                              detail_url=CHECKLIST_URL + "#vendors")
        return ToolResult(
            summary=f"유지보수 업체 {len(vs)}곳",
            data={"업체": [{k: v for k, v in x.items() if v} for x in vs]},
            detail_url=CHECKLIST_URL + "#vendors")

    lists = d.get("checklists", {})
    key = None
    if period:
        p = period.strip()
        key = PERIOD_WORDS.get(p) or next(
            (v for k, v in PERIOD_WORDS.items() if k in p), None)
        if not key:
            return fail(f"'{period}' 는 모르는 주기입니다. "
                        f"수시·매일·월간·분기·연간 중에서 알려주세요.")

    want = [key] if key else list(PERIODS)
    out: dict[str, dict] = {}
    total = 0
    for k in want:
        secs = lists.get(k, [])
        block = {}
        for sec in secs:
            items = [i.get("text") for i in sec.get("items", []) if i.get("text")]
            if items:
                block[sec.get("title", "기타")] = items
                total += len(items)
        if block:
            out[PERIODS[k]] = block

    if not out:
        return ToolResult(summary="체크리스트에 등록된 항목이 없습니다.",
                          data={"항목": {}}, detail_url=CHECKLIST_URL)

    label = PERIODS[key] if key else "전체"
    return ToolResult(
        summary=f"{label} 체크리스트 — {total}개 항목",
        data={"주기": label, "총 항목": total, "체크리스트": out,
              "작성지침": "이 목록은 그대로 답변에 적어도 됩니다. 항목이 20개를 넘으면 "
                    "구역 이름 위주로 줄이고 화면 링크를 안내하십시오. "
                    "체크 표시(완료 여부)는 사람마다 다르므로 알려주지 않습니다."},
        # 물어본 주기의 탭이 열린 채로 보낸다 (#daily 처럼).
        # 주기를 안 밝혔으면 화면이 원래 열던 탭 그대로 둔다.
        detail_url=CHECKLIST_URL + (f"#{key}" if key else ""),
    )


# ── IT 자가진단 ──────────────────────────────────────────────
#
# 직원이 "안 돼요" 하고 부르기 전에 스스로 확인할 것을 알려 주는 화면이다.
# 챗에서 물어도 같은 순서를 그대로 준다. 확인 순서가 두 벌이 되면
# 화면과 챗이 다른 말을 하게 되므로, 화면이 쓰는 그 파일을 그대로 읽는다.
#
#   /selfcheck/data/selfcheck.js   window.SELFCHECK_DATA = { ... }
#
# ★ window.SELFCHECK_DATA 라는 이름이 앱과의 약속이다. 바꾸면 못 읽는다.


def _selfcheck() -> dict:
    raw = _fetch("/selfcheck/data/selfcheck.js")
    i = raw.index("{")
    return json.loads(raw[i:].rstrip().rstrip(";"))


def _plain(s: str) -> str:
    """화면용 태그(<b>·<kbd>·<code>)를 떼고 글자만 남긴다."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def _sc_steps(topic: dict) -> list[str]:
    out = []
    for i, st in enumerate(topic.get("steps", []), 1):
        t, d = _plain(st.get("t", "")), _plain(st.get("d", ""))
        out.append(f"{i}. {t} — {d}" if d else f"{i}. {t}")
    return out


@tool(
    name="search_selfcheck",
    label="IT 자가진단",
    description=(
        "전산 문제가 생겼을 때 전산팀에 연락하기 전에 **본인이 먼저 확인할 순서**를 알려준다. "
        "'모니터가 안 나와요', '인터넷이 안 돼요', '인쇄가 안 나와요', '소리가 안 나요', "
        "'PC가 느려요', '비밀번호를 잊었어요', 'USB가 인식이 안 돼요', "
        "'화상회의에서 마이크가 안 잡혀요' 처럼 **지금 뭔가 고장났다고 말할 때** 쓴다. "
        "모니터·화면, 네트워크·인터넷, 프린터·복합기, PC·주변기기, 계정·프로그램·파일 "
        "다섯 분야에 증상 27개가 들어 있다. 확인 순서를 차례대로 돌려준다. "
        "낱말을 비우고 부르면 어떤 증상이 있는지 목록을 돌려준다. "
        "※ 시스템 사용법(SAP·NAS·그룹웨어 절차)이면 search_manual, "
        "IT 담당자의 주기별 운영 업무면 get_checklist 를 쓴다."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string",
                      "description": "증상을 그대로. '모니터가 안 나와요', '인쇄', "
                                     "'소리' 처럼. 비우면 증상 목록"},
        },
    },
    service="selfcheck",
)
def search_selfcheck(user: User, query: str = "") -> ToolResult:
    try:
        data = _selfcheck()
    except Exception as e:  # noqa: BLE001
        return _down(e, "IT 자가진단")

    topics = data.get("topics", [])
    cats = {c["id"]: c["name"] for c in data.get("cats", [])}
    q = (query or "").strip()

    # 비우고 부르면 무엇이 있는지 알려준다
    if not q:
        by_cat = {}
        for t in topics:
            by_cat.setdefault(cats.get(t.get("cat"), "기타"), []).append(t.get("title"))
        return ToolResult(
            summary=f"자가진단 증상 {len(topics)}개",
            data={"분야별 증상": by_cat,
                  "작성지침": "목록만 보여 주고, 어느 것인지 고르면 그 확인 순서를 "
                          "알려주겠다고 하십시오."},
            detail_url=SELFCHECK_URL)

    # 화면이 쓰는 것과 같은 방식으로 고른다 — 구체적인 말일수록 높은 점수.
    # 화면과 챗이 다른 증상을 집으면 그것이 곧 서로 다른 답이 된다.
    low = " ".join(q.lower().split())
    best, best_score = None, 0
    for t in topics:
        s = sum(len(k.lower().replace(" ", ""))
                for k in t.get("kw", []) if k.lower() in low)
        if s > best_score:
            best, best_score = t, s

    # 등록된 말로 못 잡으면 제목·본문에서 한 번 더 본다
    if best_score < 2:
        words = _words(q)
        need = _need(words)
        cand = []
        for t in topics:
            body = " ".join(_sc_steps(t))
            title = t.get("title", "")
            score = matched = 0
            for w in words:
                if _hit(w, title):
                    score += 3; matched += 1
                elif _hit(w, body):
                    score += 1; matched += 1
            if matched >= need and score >= 3:
                cand.append((score, t))
        if cand:
            cand.sort(key=lambda x: -x[0])
            best, best_score = cand[0][1], cand[0][0]

    if not best:
        return ToolResult(
            summary=f"자가진단에 '{q}' 에 해당하는 증상이 없습니다.",
            data={"결과": "없음",
                  "있는 분야": list(cats.values()),
                  "작성지침": "**없다고 그대로 말하십시오.** 비슷해 보이는 다른 증상을 "
                          "끌어다 답하지 마십시오. 분야를 알려주고 자가진단 화면에서 "
                          "찾아보도록 안내하십시오."},
            detail_url=SELFCHECK_URL)

    return ToolResult(
        summary=f"{cats.get(best.get('cat'), '')} — {best.get('title')}",
        data={"증상": best.get("title"),
              "확인 순서": _sc_steps(best),
              "다 해봤는데 안 될 때": "자가진단 화면에서 '다 해봤는데 안 돼요' 를 "
                                "누르면 확인한 항목이 들어간 접수 문구를 만들어 줍니다.",
              "작성지침": "확인 순서를 **번호 그대로, 위에서부터** 알려주십시오. "
                      "순서를 바꾸거나 요약하지 마십시오 — 위에서부터 하나씩 "
                      "확인하도록 만들어진 순서입니다. 다 해봐도 안 되면 "
                      "화면에서 접수 문구를 만들 수 있다고 덧붙이십시오."},
        detail_url=SELFCHECK_URL + "#" + str(best.get("id") or ""),
    )
