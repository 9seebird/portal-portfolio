"""ai-report 연결 도구.

### 이 도구가 하는 일

포털은 엑셀을 직접 읽지 않는다. **ai-report 에게 물어보고 답을 옮긴다.**

    직원: "이번 달 AI 사용량 알려줘"
        → 포털이 ai-report 의 API 를 호출
        → ai-report 가 자기 데이터로 계산해서 돌려줌
        → 포털은 그걸 한두 문장으로 줄이고, 자세한 건 링크로 안내

### 왜 파일을 직접 읽지 않는가

처음에는 포털이 같은 엑셀을 열어 직접 합계를 냈다. 그러면 **같은 계산이
두 벌**이 된다. 실제로 그렇게 짜 놓고 보니 대시보드 화면은 259만 원,
챗은 165만 원을 말하고 있었다. 둘 중 무엇이 맞는지 확인하는 데만도
시간이 걸리고, 이런 어긋남은 눈에 잘 띄지도 않는다.

앱이 자기 숫자를 책임지고 포털은 전달만 하면 이 문제가 생기지 않는다.
그리고 앞으로 앱이 늘어날 때 포털이 각 앱의 파일 형식을 알 필요가 없다.
새 앱을 붙이는 일이 "API 하나 호출하는 도구 파일 하나 추가"로 끝난다.

    [ai-report 컨테이너]  ← 엑셀·계산·화면을 전부 책임진다
            ↑ HTTP
    [포털 컨테이너]       ← 물어보고 요약해서 전달

### 붙이는 데 필요한 것

`.env` 의 `AI_REPORT_API` 하나. 같은 도커 네트워크이므로 컨테이너 이름으로 부른다.

    AI_REPORT_API=http://demo-aireport:8080

ai-report 쪽은 고칠 것이 없다. 이미 있는 엔드포인트를 쓴다.

    GET  /api/files            올라와 있는 엑셀 목록
    GET  /api/data/{filename}  그 달의 집계 (overview + userSummary)
    POST /api/upload           월별 엑셀 올리기

### 올리는 것도 같은 원칙이다

"8월 리포트 엑셀 올려줘" 를 챗에서 하려면 포털이 파일을 **앱에 넘기기만**
하면 된다. 포털이 엑셀을 뜯어보고 검증하지 않는다. 어떤 컬럼이 있어야
하는지는 ai-report 가 안다. 실제로 그 앱은 시트 이름과 필수 컬럼까지
확인하고, 아니면 이유를 돌려준다. 그 이유를 그대로 직원에게 전한다.
"""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from ..registry import User, tool
from ..schemas import ToolResult, fail

KST = ZoneInfo("Asia/Seoul")

# ── 환경에 맞게 수정할 부분 ──────────────────────────────────
# ai-report 서비스 주소. 도커에서는 컨테이너 이름으로 부른다.
#   docker : http://demo-aireport:8080
#   로컬   : http://localhost:8081
API = os.environ.get("AI_REPORT_API", "http://demo-aireport:8080").rstrip("/")

# 직원이 눌러서 들어갈 주소. nginx 경로와 맞춘다.
REPORT_URL = os.environ.get("AI_REPORT_URL", "/ai-report/")

# 앱이 죽어 있을 때 챗 전체가 멈추면 안 된다. 짧게 끊는다.
TIMEOUT = float(os.environ.get("AI_REPORT_TIMEOUT", "5"))

# 답변에 직접 나열할 최대 인원. 넘으면 링크로 안내한다.
TOP_N = 5

# 사람이 아닌 계정(감사로그·IP허용 등 부가서비스). 순위에서 뺀다.
SYSTEM_RE = re.compile(r"^__system__", re.I)
# ────────────────────────────────────────────────────────────


# 서버에서 서버로 부르는 통로임을 밝히는 공유 토큰.
# 브라우저가 아니라 쿠키가 없으므로, 이 토큰으로 "포탈이 부른 것"임을 알린다.
# 포탈은 사용자 권한을 확인한 뒤에만 이 도구를 노출하므로,
# 포탈이 물어봤다는 것 자체가 그 사용자에게 권한이 있다는 뜻이다.
SERVICE_TOKEN = os.environ.get("AUDIT_TOKEN", "")


def _get(path: str):
    """ai-report 에 GET. 실패하면 예외를 그대로 올린다."""
    headers = {"Accept": "application/json"}
    if SERVICE_TOKEN:
        headers["X-Service-Token"] = SERVICE_TOKEN
    req = urllib.request.Request(API + path, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _files() -> dict[str, str]:
    """{'2026-07': '2026_07.xlsx', ...} — 올라와 있는 달."""
    out = {}
    for f in _get("/api/files"):
        name = f.get("name", "")
        m = re.search(r"(20\d{2})[_-]?(\d{2})", name)
        if m:
            out[f"{m.group(1)}-{m.group(2)}"] = name
    return dict(sorted(out.items()))


def _resolve_month(month: str | None, have: dict) -> str:
    """'2026-08' 형태로 정규화. 미지정이면 자료가 있는 가장 최근 달."""
    if not month:
        now = datetime.now(KST).strftime("%Y-%m")
        # 이번 달 파일이 아직 안 올라왔으면 가장 최근 달로 답한다.
        # "자료가 없습니다"보다 "지난달 기준입니다"가 쓸모 있다.
        return now if (now in have or not have) else list(have)[-1]

    digits = [int(s) for s in re.findall(r"\d+", month)]
    if len(digits) == 1 and 1 <= digits[0] <= 12:
        return f"{datetime.now(KST).year}-{digits[0]:02d}"
    if len(digits) >= 2:
        return f"{digits[0]}-{digits[1]:02d}"
    return month


def _won(v) -> str:
    return f"{int(round(float(v or 0))):,}원"


def _people(rows: list[dict]) -> list[dict]:
    """사람 계정만, 요금 많은 순."""
    out = []
    for r in rows:
        name = str(r.get("name") or "").strip()
        if not name or name.lower() == "nan" or SYSTEM_RE.match(name):
            continue
        out.append({"name": name,
                    "charge": float(r.get("totalCharge") or 0),
                    "calls": int(r.get("totalUsageCount") or 0)})
    return sorted(out, key=lambda x: x["charge"], reverse=True)


@tool(
    name="upload_ai_report",
    label="AI 리포트 엑셀 올리기",
    description=(
        "챗에 첨부한 엑셀을 AI 리포트 서비스에 올린다. "
        "'이 파일 리포트에 올려줘', '8월 사용량 엑셀 등록해줘', "
        "'이거 리포트에 반영해줘' 처럼 **엑셀을 첨부한 상태에서** "
        "그 파일을 AI 리포트에 넣어 달라고 할 때 쓴다. "
        "올린 뒤에는 get_ai_usage 로 그 달을 조회할 수 있다. "
        "웍스AI 원본(Raw Data) 엑셀이나 이용통계 집계 엑셀만 받는다 — "
        "형식이 맞지 않으면 앱이 이유를 돌려주므로 그대로 전달하면 된다. "
        "파일 이름이 '2026_08.xlsx' 처럼 연월을 담고 있어야 그 달로 잡힌다. "
        "※ 파일 내용을 요약하거나 분석해 달라는 것이면 이 도구가 아니라 "
        "read_attached_file 을 쓴다. 이 도구는 **등록**만 한다."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "첨부한 엑셀의 file_id. [이 대화에 붙은 파일] 목록에 있다.",
            },
        },
        "required": ["file_id"],
    },
    service="ai-report",
)
def upload_ai_report(user: User, file_id: str) -> ToolResult:
    from .. import uploads

    got = uploads.read(file_id, user.user_id)
    if not got:
        return fail("첨부한 파일을 찾지 못했습니다. 파일을 다시 올려주세요.")
    meta, blob = got
    if meta["user_id"] != user.user_id:
        return fail("본인이 올린 파일만 등록할 수 있습니다.")
    if (meta["ext"] or "").lower() not in ("xlsx", "xlsm"):
        return fail(f"AI 리포트는 엑셀(.xlsx)만 받습니다. 올리신 것은 .{meta['ext']} 입니다.")

    body, content_type = uploads.multipart("file", meta["name"], blob)
    req = urllib.request.Request(API + "/api/upload", data=body, method="POST")
    req.add_header("Content-Type", content_type)
    if SERVICE_TOKEN:
        req.add_header("X-Service-Token", SERVICE_TOKEN)
    # 누가 올렸는지 앱 기록에 남게 한다. 한글은 헤더에 그대로 못 넣는다.
    req.add_header("X-User-Id", user.user_id)
    req.add_header("X-User-Name", urllib.parse.quote(user.name or ""))
    req.add_header("X-User-Dept", urllib.parse.quote(user.dept or ""))

    try:
        # 파일 전송은 조회보다 오래 걸린다. 조회용 짧은 시간을 쓰면 끊긴다.
        with urllib.request.urlopen(req, timeout=max(TIMEOUT, 60)) as r:
            res = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        if e.code in (401, 403):
            return fail("AI 리포트 서비스가 등록을 거절했습니다. "
                        "권한 설정이나 서비스 토큰(AUDIT_TOKEN)을 확인해 주세요.")
        return fail(f"AI 리포트에 올리지 못했습니다. (HTTP {e.code}) {detail}")
    except urllib.error.URLError as e:
        return fail(f"AI 리포트 서비스에 연결하지 못했습니다. ({API}) — {e.reason}")
    except Exception as e:  # noqa: BLE001
        return fail(f"AI 리포트에 올리지 못했습니다. {type(e).__name__}")

    # 앱은 실패도 200 으로 돌려준다 (success=false). 그대로 믿으면 안 된다.
    if not res.get("success"):
        why = res.get("error") or "형식이 맞지 않습니다."
        return ToolResult(summary=f"등록하지 못했습니다 — {why}",
                          data={"등록됨": False, "이유": why}, detail_url=REPORT_URL)

    d = res.get("data") or {}
    rows = d.get("rows")
    return ToolResult(
        summary=(f"{d.get('name', meta['name'])} 을(를) AI 리포트에 등록했습니다."
                 + (f" ({rows:,}행)" if rows else "")
                 + " 이제 그 달 사용량을 조회할 수 있습니다."),
        data={"등록됨": True, "파일명": d.get("name"),
              "행수": rows, "크기": d.get("size")},
        detail_url=REPORT_URL,
    )


@tool(
    name="get_ai_usage",
    label="AI 사용 현황 조회",
    description=(
        "사내 AI 서비스 사용 현황을 조회한다. "
        "총 비용, 총 호출 수, 사용 인원, 사용자 순위를 돌려준다. "
        "'이번 달 AI 비용 얼마야', 'AI 사용량 알려줘', 'AI 사용료', "
        "'누가 얼마나 썼어', '지난달 비용', '내 사용량' 등 "
        "AI 사용에 관한 질문 전반에 사용한다. "
        "월을 지정하지 않으면 최근 달로 조회하므로 사용자에게 되물을 필요가 없다. "
        "인원이 많으면 목록 대신 상세 화면 링크를 안내한다."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "month": {
                "type": "string",
                "description": "조회할 월. 'YYYY-MM' 형식. 미지정 시 최근 달.",
            },
            "target_user": {
                "type": "string",
                "description": "특정 사용자만 조회할 때 이름을 지정. 미지정 시 전체.",
            },
        },
    },
    # 이 도구는 ai-report 서비스에 속한다.
    # 관리자 화면에서 그 서비스의 접근 범위를 바꾸면 여기에도 즉시 반영된다.
    service="ai-report",
)
def get_ai_usage(
    user: User, month: str | None = None, target_user: str | None = None
) -> ToolResult:
    try:
        have = _files()
    except urllib.error.URLError as e:
        # 앱이 내려가 있는 것과 데이터가 없는 것은 다른 상황이다.
        # 뭉뚱그리면 "자료가 없다"는 잘못된 답이 나간다.
        return fail(f"AI 리포트 서비스에 연결하지 못했습니다. ({API}) — {e.reason}")
    except Exception as e:  # noqa: BLE001
        return fail(f"AI 리포트 서비스 응답이 올바르지 않습니다. {type(e).__name__}: {e}")

    ym = _resolve_month(month, have)
    url = f"{REPORT_URL}?month={ym}"

    if not have:
        return fail("아직 올라온 사용 내역이 없습니다. "
                    "AI 리포트 화면에서 월별 엑셀을 먼저 올려야 합니다.")
    if ym not in have:
        return ToolResult(
            summary=(f"{ym} 자료가 아직 없습니다. "
                     f"현재 올라와 있는 달은 {', '.join(have)} 입니다."),
            data={"month": ym, "available_months": list(have)},
            detail_url=REPORT_URL,
        )

    try:
        d = _get(f"/api/data/{urllib.parse.quote(have[ym])}")
    except Exception as e:  # noqa: BLE001
        return fail(f"{ym} 자료를 가져오지 못했습니다. {type(e).__name__}: {e}")
    if "error" in d:
        return fail(f"{ym} 자료를 읽지 못했습니다. {d['error']}")

    ov = d.get("overview", {})
    ranked = _people(d.get("userSummary", []))

    # ── 특정 사용자 ──────────────────────────────────────────
    if target_user:
        hit = [r for r in ranked if target_user in r["name"]]
        if not hit:
            return ToolResult(
                summary=f"{ym} 사용 내역에서 '{target_user}'님을 찾지 못했습니다.",
                data={"month": ym}, detail_url=url,
            )
        me = hit[0]
        rank = ranked.index(me) + 1
        return ToolResult(
            summary=(f"{ym} {me['name']}님의 AI 사용비용은 {_won(me['charge'])}입니다. "
                     f"사용 {me['calls']:,}회, 전체 {len(ranked)}명 중 {rank}위입니다."),
            data={"month": ym, "name": me["name"], "charge": int(me["charge"]),
                  "calls": me["calls"], "rank": rank, "of": len(ranked)},
            detail_url=f"{url}&user={me['name']}",
        )

    # ── 전체 ─────────────────────────────────────────────────
    total = ov.get("totalCharge", 0)
    calls = int(ov.get("totalUsage", 0) or 0)
    users = int(ov.get("totalUsers", 0) or 0)

    summary = (f"{ym} 사내 AI 사용비용은 {_won(total)}입니다. "
               f"총 호출 {calls:,}회, 사용 인원 {users}명입니다.")
    if ranked:
        top = ", ".join(f"{r['name']} {_won(r['charge'])}" for r in ranked[:3])
        summary += f" 많이 쓴 순으로 {top} 입니다."
    if len(ranked) > TOP_N:
        # 50명을 다 읊으면 답변이 아니라 목록이 된다.
        # 상위 몇 명만 말하고 나머지는 화면으로 넘긴다.
        summary += f" 전체 {len(ranked)}명의 순위는 리포트 화면에서 확인하세요."

    return ToolResult(
        summary=summary,
        data={
            "month": ym,
            "date_range": ov.get("dateRange", ""),
            "total_charge": int(round(float(total or 0))),
            "total_calls": calls,
            "total_users": users,
            "top_users": [{"name": r["name"], "charge": int(r["charge"]),
                           "calls": r["calls"]} for r in ranked[:TOP_N]],
        },
        detail_url=url,
        truncated=len(ranked) > TOP_N,
    )
