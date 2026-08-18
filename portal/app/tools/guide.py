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
        "찾은 절차의 글자를 그대로 돌려주며, 화면 캡처는 매뉴얼 화면에서 봐야 한다."
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
    words = [w for w in q.split() if w] or [q]

    # 어디에서 걸렸는지에 따라 무게를 다르게 준다.
    # "SAP 신규 엔트리" 를 찾을 때 'SAP' 하나만 걸린 항목이 28개나 나오면
    # 맞는 답이 그 속에 묻힌다. 항목 이름에서 걸린 것이 가장 정확하다.
    def has(w: str, text: str) -> bool:
        return w in text or w.replace(" ", "") in text.replace(" ", "")

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
                if has(w, sec_title):
                    score += 3; matched += 1
                elif has(w, body):
                    score += 2; matched += 1
                elif has(w, man_title):
                    score += 1; matched += 1
            if not matched:
                continue
            # 여러 낱말로 물었으면 다 걸린 쪽을 크게 앞세운다
            score += matched * 2
            hits.append((score, m, sec, steps, idx))

    if not hits:
        titles = ", ".join(m.get("title", "") for m in manuals)
        return ToolResult(
            summary=f"'{q}' 로 찾은 대목이 없습니다. 다른 말로 찾아보시거나 "
                    f"매뉴얼 화면에서 직접 살펴보세요.",
            data={"결과": "없음", "있는 매뉴얼": titles},
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
        "유지보수 업체 연락처도 함께 들어 있다."
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
