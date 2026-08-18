"""사업계획 예상손익(biz-plan) 연결 도구.

포털은 손익을 계산하지 않는다. 파일 두 개를 그대로 앱에 넘기고 요약만 받아 온다.
계산은 전부 앱이 한다. (본보기: _파일도구_본보기.py.txt)

    직원이 챗에 마스터·매출목표 두 파일을 붙임
        → 포털이 보관하고 file_id 를 만든다
        → 이 도구가 두 파일을 앱의 /api/analyze 로 넘긴다
        → 앱이 **점검하고** 계산한다
        → 챗에는 요약만. 표는 앱 화면에서 본다

### 점검에서 걸리면 숫자를 안 준다

이 앱의 위험은 「틀렸는데 표는 멀쩡히 나오는 것」이다. 채널 이름 하나가
어긋나면 그 채널 매출이 통째로 빠지는데 아무 표시가 없다. 실제로 원작자가
준 예시 파일이 9천만 원을 흘리고 있었다.

그래서 앱이 합계를 맞춰 보고, 안 맞으면 **결과를 아예 안 보낸다.**
그때 이 도구가 할 일은 **그 이유를 그대로 전하는 것**이다. 요약해서
"확인이 필요합니다" 로 뭉개면 안 된다 — 얼마가 왜 빠졌는지가 답이다.

### 어느 파일이 무엇인지

**모델이 이름을 보고 고른다.** 둘이 뒤집히면 앱이 알아채고 "자리가 바뀐 것
같습니다" 라고 알려 주지만, 그래도 답의 첫 줄에 무엇을 무엇으로 봤는지
적게 한다.
"""

import base64
import json
import os
import urllib.error
import urllib.request
from urllib.parse import quote

from .. import uploads
from ..registry import User, tool
from ..schemas import ToolResult, fail

# 앱 주소 — 같은 도커 네트워크이므로 컨테이너 이름으로 부른다
API = os.environ.get("BIZPLAN_API", "http://demo-biz-plan:8080").rstrip("/")

# 직원이 눌러서 들어갈 주소 — nginx 경로와 맞춘다
APP_URL = os.environ.get("BIZPLAN_URL", "/biz-plan/")

# 계산 0.4초 · 엑셀 3개 1.4초. 금방 끝나므로 시간 여유를 크게 둘 필요가 없다.
# 그래도 사내망에서 파일이 오가는 시간이 있으니 여유를 둔다.
TIMEOUT = float(os.environ.get("BIZPLAN_TIMEOUT", "120"))

SERVICE_TOKEN = os.environ.get("AUDIT_TOKEN", "")


def _headers(user: User) -> dict:
    h = {"Accept": "application/json", "Content-Type": "application/json"}
    if SERVICE_TOKEN:
        # 사람이 아니라 포털이 부른 것임을 알린다
        h["X-Service-Token"] = SERVICE_TOKEN
    # 앱 쪽 기록에 "누가 요청했는지"가 남게 한다.
    # ★ 이름·부서는 한글이라 **그대로 넣으면 안 된다.** HTTP 헤더는 latin-1
    #   로만 담기므로 urllib 이 보내기 직전에 UnicodeEncodeError 를 낸다.
    #   파일과 아무 상관이 없는데도 화면에는 "인코딩 오류" 라고만 떠서
    #   원인을 찾기 어렵다. nginx 가 앱에 넘길 때와 같은 방식으로 퍼센트
    #   인코딩한다 (앱 쪽 auth.py 가 unquote 로 되돌린다).
    h["X-User-Id"] = user.user_id
    h["X-User-Name"] = quote(user.name or "")
    h["X-User-Dept"] = quote(user.dept or "")
    return h


def _won(v) -> str:
    try:
        return f"{round(float(v)):,}"
    except (TypeError, ValueError):
        return str(v)


@tool(
    name="analyze_biz_plan",
    label="사업계획 예상손익",
    description=(
        "사업계획용 예상손익을 계산한다. "
        "'예상손익 뽑아줘', '사업계획 손익 계산해줘', '내년 계획 손익 좀', "
        "'채널별 손익 어떻게 나와' 처럼 **파일이 첨부된 상태에서** 묻는 질문에 쓴다."
        "\n"
        "파일이 **두 개** 필요하다 — 마스터(사업계획용 기본양식), 매출목표·비용. "
        "[첨부한 파일] 목록의 이름을 보고 어느 것이 무엇인지 정한다 "
        "(마스터는 보통 '기본양식' 또는 '마스터', 나머지는 '매출목표' 또는 '비용'). "
        "둘이 다 붙어 있지 않으면 이 도구를 부르지 말고, 무엇이 빠졌는지 알려 주고 "
        "그 파일을 올려 달라고 안내한다."
        "\n"
        "답할 때 **어느 파일을 무엇으로 봤는지 먼저 밝힌다.** "
        "점검에 걸려 결과가 안 왔을 때는 **그 이유를 줄여 쓰지 말고 그대로 전한다** — "
        "얼마가 왜 빠졌는지와 어떻게 고치는지가 그 답의 전부다. "
        "표 전체는 챗에 옮기지 말고 앱 화면에서 보도록 안내한다."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "master_file_id": {
                "type": "string",
                "description": "마스터 파일(사업계획용 기본양식)의 file_id.",
            },
            "sales_file_id": {
                "type": "string",
                "description": "매출목표·비용 파일의 file_id.",
            },
        },
        "required": ["master_file_id", "sales_file_id"],
    },
    service="biz-plan",
)
def analyze_biz_plan(user: User, master_file_id: str = "",
                     sales_file_id: str = "") -> ToolResult:
    if not (master_file_id and sales_file_id):
        return fail("마스터 양식과 매출목표·비용 두 파일을 모두 붙여 주세요.")

    slots = [("base", master_file_id, "마스터"),
             ("sales", sales_file_id, "매출목표·비용")]

    blobs, used, keep = {}, [], []
    for field, fid, what in slots:
        # **본인이 올린 것만** 나온다. 남의 file_id 를 넣어도 여기서 None 이 된다.
        one = uploads.read(fid, user.user_id)
        if not one:
            return fail(f"{what} 파일을 찾지 못했습니다. 파일을 다시 올려주세요.")
        meta, blob = one
        blobs[field] = base64.b64encode(blob).decode()
        used.append(f"{what}={meta['name']}")
        keep.append(fid)

    if blobs["base"] == blobs["sales"]:
        return fail("두 자리에 같은 파일이 들어갔습니다. "
                    "마스터 양식과 매출목표·비용을 각각 다른 파일로 골라 주세요.")

    body = json.dumps({"base_b64": blobs["base"], "sales_b64": blobs["sales"]}).encode()
    req = urllib.request.Request(API + "/api/analyze", data=body,
                                 headers=_headers(user), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail", "")
        except Exception:  # noqa: BLE001
            pass
        if e.code == 413:
            return fail(detail or "파일이 너무 큽니다.")
        return fail(detail or f"예상손익 서비스가 요청을 거절했습니다. (HTTP {e.code})")
    except urllib.error.URLError as e:
        # 앱이 꺼져 있는 것과 계산이 안 되는 것은 다른 상황이다.
        return fail(f"예상손익 서비스에 연결하지 못했습니다. ({API}) — {e.reason}")
    except Exception as e:  # noqa: BLE001
        return fail(f"예상손익 계산에 실패했습니다. {type(e).__name__}: {e}")

    # 앱에 무사히 넘어갔을 때만 포털 사본을 지운다.
    # ★ 실패했을 때 지우면 안 된다. 다시 해 보려 해도 파일이 이미 없어서
    #   "파일을 찾지 못했습니다" 가 되고, 직원은 두 파일을 다시 올려야 한다.
    for fid in keep:
        try:
            uploads.remove(fid, user.user_id)
        except Exception:  # noqa: BLE001
            pass

    seen = f"[{', '.join(used)} 로 봤습니다] "
    checks = d.get("checks") or []
    stops = [c["text"] for c in checks if c.get("level") == "stop"]
    warns = [c["text"] for c in checks if c.get("level") == "warn"]

    # ── 점검에서 걸렸다 — 숫자는 오지 않는다 ────────────────────
    if not d.get("ok"):
        # 이유를 **그대로** 넘긴다. 줄여 쓰면 무엇을 고쳐야 하는지가 사라진다.
        return ToolResult(
            summary=(seen + "점검에서 걸려 계산 결과를 내지 않았습니다. "
                     "아래 내용을 확인하고 파일을 고쳐서 다시 올려 주세요.\n\n"
                     + "\n\n".join(stops or ["이유를 알 수 없습니다."])),
            data={"checks": checks},
            detail_url=APP_URL,
        )

    # ── 통과 ────────────────────────────────────────────────────
    s = d.get("summary") or {}
    line = " · ".join(f"{k} {_won(v)}" for k, v in s.items())
    extra = ""
    if warns:
        extra = "\n\n확인해 주세요 — " + " / ".join(warns)
    return ToolResult(
        summary=(seen + f"연간 합계는 {line} 입니다. "
                 f"고객그룹 {len(d.get('cg_list') or [])}개, "
                 f"브랜드 {len(d.get('br_list') or [])}개 기준입니다. "
                 "월별·채널별 표와 엑셀 내려받기는 앱 화면에서 보실 수 있습니다."
                 + extra),
        data={"summary": s, "cg_list": d.get("cg_list"), "br_list": d.get("br_list"),
              "checks": checks},
        detail_url=APP_URL,
    )
