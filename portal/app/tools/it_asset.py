"""자산관리(it-asset) 연결 도구.

### 이 도구가 하는 일

포털은 자산 DB 를 직접 읽지 않는다. **자산관리 앱에 물어보고 답을 옮긴다.**

    직원: "홍길동이 쓰는 장비 뭐 있어?"
        → 포털이 자산관리의 API 를 호출
        → 자산관리가 자기 DB 로 찾아서 돌려줌
        → 포털은 그걸 문장으로 줄이고, 자세한 건 링크로 안내

### 어디서 왔나

`it-portal/mcp/asset_mcp.py` (클로드 데스크톱용으로 만들어 둔 MCP 서버)를
그대로 옮긴 것이다. 부르는 엔드포인트도, 도구를 나눈 기준도 같다.
이미 써 보면서 "이런 질문이 들어온다"가 검증된 묶음이라 새로 설계하지 않았다.

바뀐 것은 인증 방식 하나다.

    MCP  : admin/admin1234 로 로그인해서 JWT 를 받아 붙였다
    포털 : 로그인이 없다. 지금 챗을 쓰는 사람의 정보를 헤더로 붙인다

그래서 자산관리 앱 입장에서는 "그 직원이 직접 조회한 것"과 똑같이 보인다.
누가 무엇을 조회했는지가 앱 쪽 기록에도 그 사람 이름으로 남는다.

### 권한

이 파일의 모든 도구는 `service="it-asset"` 이다.
포털 관리자 화면에서 자산관리의 접근 범위를 바꾸면 챗에도 즉시 반영된다.
범위 밖 사람에게는 이 도구들이 **목록에 아예 보이지 않고**, 실행도 막힌다.

역할은 항상 `user` 로 보낸다. 챗은 조회만 하기 때문이다.
삭제·수정은 화면에서 담당자가 한다.

### 붙이는 데 필요한 것

`.env` 두 줄. 같은 도커 네트워크이므로 컨테이너 이름으로 부른다.

    IT_ASSET_API=http://demo-asset-api:8000
    IT_ASSET_URL=/it-asset/

`asset-web` 이 아니라 **`asset-api`** 다. 화면(nginx)을 거칠 이유가 없다.
자산관리 쪽은 고칠 것이 없다. 이미 있는 엔드포인트를 쓴다.

    GET /dashboard/summary        전체 요약
    GET /dashboard/breakdown      종류별·상태별 집계
    GET /assets/                  자산 목록 (asset_type, status, employee_id 로 거름)
    GET /employees/               직원 목록 (name, department, status 로 거름)
    GET /license-pools/expiring   만료 임박 라이선스
    GET /software-products        소프트웨어 제품 목록
"""

import json
import re
import os
import urllib.error
import urllib.parse
import urllib.request

from ..registry import User, tool
from ..schemas import ToolResult, fail

# ── 환경에 맞게 수정할 부분 ──────────────────────────────────
#   docker : http://demo-asset-api:8000   (컨테이너 이름)
#   로컬   : http://localhost:8000
API = os.environ.get("IT_ASSET_API", "http://demo-asset-api:8000").rstrip("/")

# 직원이 눌러서 들어갈 주소. nginx 경로와 맞춘다.
ASSET_URL = os.environ.get("IT_ASSET_URL", "/it-asset/")


def _at(view: str = "") -> str:
    """자산관리 앱의 **그 화면**으로 가는 주소.

    바로가기를 눌렀는데 늘 대시보드가 열리면, 누른 사람이 왼쪽 메뉴에서
    한 번 더 찾아 들어가야 한다. 자리를 물었으면 자리 배치가 열려야 한다.

    앱이 해시(#seats)를 읽어 그 화면으로 바로 간다 (frontend/app.js).
    경로가 아니라 해시인 이유 — 이 앱은 /it-asset/ 아래에 붙어 있어서
    경로를 바꾸면 새로고침할 때 서버가 없는 경로를 찾다가 404 를 낸다.
    """
    base = ASSET_URL if ASSET_URL.endswith("/") else ASSET_URL + "/"
    return base + ("#" + view if view else "")

# 앱이 죽어 있을 때 챗 전체가 멈추면 안 된다. 짧게 끊는다.
TIMEOUT = float(os.environ.get("IT_ASSET_TIMEOUT", "5"))

# 답변에 직접 나열할 최대 건수. 넘으면 "화면에서 보라"고 안내한다.
# 챗 답변에 50줄짜리 표가 나오면 읽지 않는다.
MAX_ROWS = 15
# ────────────────────────────────────────────────────────────


def _get(path: str, params: dict | None = None, user: User | None = None):
    """자산관리에 GET. 지금 챗을 쓰는 사람의 정보를 헤더로 붙인다.

    이 요청은 nginx 를 거치지 않고 포털 → 앱 으로 바로 간다.
    그래서 헤더를 여기서 직접 붙여야 한다. 안 붙이면 앱이 401 로 막는다.

    권한 검사는 이 함수가 아니라 registry 가 이미 했다.
    도구가 실행됐다는 것 자체가 그 사람에게 자산관리 권한이 있다는 뜻이다.
    """
    clean = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    url = API + path + ("?" + urllib.parse.urlencode(clean) if clean else "")

    headers = {"Accept": "application/json"}
    if user is not None:
        headers["X-User-Id"] = user.user_id
        # 한글은 헤더에 그대로 담을 수 없다. 앱이 unquote 해서 읽는다.
        headers["X-User-Name"] = urllib.parse.quote(user.name or "")
        headers["X-User-Dept"] = urllib.parse.quote(user.dept or "")
        # 챗은 조회만 한다. 관리자가 물어도 여기서는 user 로 보낸다.
        headers["X-User-Role"] = "user"

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _cap(rows: list) -> tuple[list, int, bool]:
    """건수가 많으면 잘라내고, 잘렸다는 사실을 같이 돌려준다."""
    rows = rows or []
    return rows[:MAX_ROWS], len(rows), len(rows) > MAX_ROWS


def _down(e: Exception) -> ToolResult:
    """앱이 내려가 있는 것과 자료가 없는 것은 다른 상황이다.

    뭉뚱그리면 "자산이 없습니다"라는 잘못된 답이 나간다.
    """
    if isinstance(e, urllib.error.HTTPError) and e.code in (401, 403):
        return fail("자산관리 서비스가 이 요청을 거절했습니다. "
                    "IT 담당자에게 문의해주세요.")
    if isinstance(e, urllib.error.URLError):
        return fail(f"자산관리 서비스에 연결하지 못했습니다. ({API}) — {e.reason}")
    return fail(f"자산관리 서비스 응답이 올바르지 않습니다. {type(e).__name__}: {e}")


def _label(row: dict) -> str:
    """자산 한 줄을 사람이 읽는 형태로."""
    parts = [row.get("asset_type"), row.get("model_name") or row.get("model"),
             row.get("asset_tag") or row.get("serial_number")]
    return " ".join(str(p) for p in parts if p) or "(이름 없음)"


# ─────────────────────────────────────────────────────────────
# 1. 전체 현황
# ─────────────────────────────────────────────────────────────
@tool(
    name="get_asset_summary",
    label="자산 현황 조회",
    description=(
        "사내 IT 자산 현황을 한눈에 요약한다. "
        "전체 자산 수, 사용 중인 수, 보관 중인 수, 수리 중인 수, "
        "만료가 임박한 렌탈 계약·라이선스 건수, IP 사용률을 돌려준다. "
        "'자산 현황 알려줘', '지금 자산 몇 대야', '자산 얼마나 있어', "
        "'IP 얼마나 남았어' 같은 질문에 쓴다."
    ),
    service="it-asset",
)
def get_asset_summary(user: User) -> ToolResult:
    try:
        d = _get("/dashboard/summary", user=user)
    except Exception as e:  # noqa: BLE001
        return _down(e)

    bits = []
    for key, label in (("total_assets", "전체"), ("assigned_assets", "사용 중"),
                       ("storage_assets", "보관"), ("repair_assets", "수리 중")):
        if d.get(key) is not None:
            bits.append(f"{label} {d[key]}대")
    return ToolResult(
        summary="자산 현황 — " + (", ".join(bits) if bits else "집계값을 받지 못했습니다"),
        data=d,
        detail_url=_at("dashboard"),
    )


# ─────────────────────────────────────────────────────────────
# 2. 종류별·상태별 집계
# ─────────────────────────────────────────────────────────────
@tool(
    name="get_asset_breakdown",
    label="자산 종류별 집계",
    description=(
        "자산을 종류별·상태별로 몇 대씩 있는지 집계해서 돌려준다. "
        "'노트북 몇 대야', '모니터 재고 얼마나 남았어', '종류별로 알려줘', "
        "'사용 중인 게 몇 대야' 같은 질문에 쓴다."
    ),
    service="it-asset",
)
def get_asset_breakdown(user: User) -> ToolResult:
    try:
        d = _get("/dashboard/breakdown", user=user)
    except Exception as e:  # noqa: BLE001
        return _down(e)
    return ToolResult(summary="자산 종류별·상태별 집계입니다.", data=d,
                      detail_url=_at("dashboard"))


# ─────────────────────────────────────────────────────────────
# 3. 자산 검색
# ─────────────────────────────────────────────────────────────
@tool(
    name="search_assets",
    label="자산 검색",
    description=(
        "자산 목록을 조회한다. 종류(asset_type)와 상태(status)로 걸러낼 수 있다. "
        "'보관 중인 노트북 뭐 있어', '수리 중인 장비 알려줘' 같은 질문에 쓴다. "
        "어떤 값이 실제로 쓰이는지 모르면 get_asset_breakdown 을 먼저 부른다. "
        "건수가 많으면 일부만 보여주고 화면으로 안내한다."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "asset_type": {"type": "string",
                           "description": "자산 종류. 예: LAPTOP, DESKTOP, MONITOR"},
            "status": {"type": "string",
                       "description": "자산 상태. 예: IN_USE, STORAGE, REPAIR"},
        },
    },
    service="it-asset",
)
def search_assets(user: User, asset_type: str | None = None,
                  status: str | None = None) -> ToolResult:
    try:
        rows = _get("/assets/", {"asset_type": asset_type, "status": status}, user=user)
    except Exception as e:  # noqa: BLE001
        return _down(e)

    items, total, cut = _cap(rows)
    cond = " · ".join(x for x in (asset_type, status) if x) or "전체"
    if total == 0:
        return ToolResult(summary=f"조건({cond})에 해당하는 자산이 없습니다.",
                          data={"total": 0}, detail_url=_at("assets"))
    return ToolResult(
        summary=f"{cond} 자산 {total}건" + (f" (앞 {len(items)}건만 표시)" if cut else ""),
        data={"total": total, "shown": len(items),
              "items": [{"이름": _label(r), "상태": r.get("status"),
                         "사용자": r.get("employee_name")} for r in items]},
        detail_url=_at("assets"),
        truncated=cut,
    )


# ─────────────────────────────────────────────────────────────
# 4. 직원 검색
# ─────────────────────────────────────────────────────────────
@tool(
    name="search_employees",
    label="직원 검색",
    description=(
        "직원 목록을 조회한다. 이름 일부·부서·재직상태로 걸러낼 수 있다. "
        "'인사총무팀 누구누구 있어', '홍씨 성 가진 사람' 같은 질문에 쓴다. "
        "특정 직원이 무슨 장비를 쓰는지 궁금한 것이면 "
        "이 도구가 아니라 get_employee_assets 를 쓴다."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "이름 일부만 넣어도 찾는다"},
            "department": {"type": "string", "description": "부서명. 예: 인사총무팀"},
            "status": {"type": "string", "description": "재직 상태"},
        },
    },
    service="it-asset",
)
def search_employees(user: User, name: str | None = None,
                     department: str | None = None,
                     status: str | None = None) -> ToolResult:
    try:
        rows = _get("/employees/",
                    {"name": name, "department": department, "status": status},
                    user=user)
    except Exception as e:  # noqa: BLE001
        return _down(e)

    items, total, cut = _cap(rows)
    cond = " · ".join(x for x in (name, department, status) if x) or "전체"
    if total == 0:
        return ToolResult(summary=f"조건({cond})에 해당하는 직원이 없습니다.",
                          data={"total": 0}, detail_url=_at("employees"))
    return ToolResult(
        summary=f"{cond} 직원 {total}명" + (f" (앞 {len(items)}명만 표시)" if cut else ""),
        data={"total": total, "shown": len(items),
              "items": [{"이름": r.get("name"), "부서": r.get("department"),
                         "상태": r.get("status")} for r in items]},
        detail_url=_at("employees"),
        truncated=cut,
    )


# ─────────────────────────────────────────────────────────────
# 5. 직원별 보유 장비  ← 가장 많이 물어볼 것
# ─────────────────────────────────────────────────────────────
@tool(
    name="get_employee_assets",
    label="직원 보유 장비 조회",
    description=(
        "특정 직원에게 지금 할당돼 있는 자산 목록을 돌려준다. "
        "'홍길동이 쓰는 장비 뭐 있어?', '김대리 노트북 뭐 써', "
        "'내 장비 알려줘' 같은 질문에 쓴다. "
        "같은 이름이 여러 명이면 후보를 먼저 알려주므로 부서를 되물으면 된다."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "직원 이름. 일부만 넣어도 찾는다"},
        },
        "required": ["name"],
    },
    service="it-asset",
)
def get_employee_assets(user: User, name: str) -> ToolResult:
    try:
        people = _get("/employees/", {"name": name}, user=user)
    except Exception as e:  # noqa: BLE001
        return _down(e)

    if not people:
        return ToolResult(summary=f"'{name}' 으로 찾은 직원이 없습니다.",
                          data={}, detail_url=_at("workspace"))

    if len(people) > 1:
        # 되물을 수 있게 후보를 준다. 임의로 한 명을 고르면 엉뚱한 답이 된다.
        return ToolResult(
            summary=f"'{name}' 으로 찾은 직원이 {len(people)}명입니다. 부서를 알려주시면 좁힐 수 있습니다.",
            data={
                  "후보": [{"이름": p.get("name"), "부서": p.get("department")}
                                 for p in people[:10]]},
            detail_url=_at("workspace"),
        )

    person = people[0]
    try:
        rows = _get("/assets/", {"employee_id": person.get("id")}, user=user)
    except Exception as e:  # noqa: BLE001
        return _down(e)

    items, total, cut = _cap(rows)
    who = f"{person.get('name')}({person.get('department')})"
    if total == 0:
        return ToolResult(summary=f"{who} 님에게 할당된 자산이 없습니다.",
                          data={"employee": who, "total": 0}, detail_url=_at("workspace"))
    return ToolResult(
        summary=f"{who} 님 보유 자산 {total}건",
        data={"employee": who, "total": total,
              "items": [{"이름": _label(r), "상태": r.get("status")} for r in items]},
        detail_url=_at("workspace"),
        truncated=cut,
    )


# ─────────────────────────────────────────────────────────────
# 6. 만료 임박 라이선스
# ─────────────────────────────────────────────────────────────
@tool(
    name="get_expiring_licenses",
    label="만료 임박 라이선스 조회",
    description=(
        "만료가 임박한 소프트웨어 라이선스 목록을 돌려준다. "
        "'곧 만료되는 라이선스 있어?', '이번 달 갱신해야 할 거 뭐야', "
        "'라이선스 언제 끝나' 같은 질문에 쓴다."
    ),
    service="it-asset",
)
def get_expiring_licenses(user: User) -> ToolResult:
    try:
        rows = _get("/license-pools/expiring", user=user)
    except Exception as e:  # noqa: BLE001
        return _down(e)

    items, total, cut = _cap(rows)
    if total == 0:
        return ToolResult(summary="만료가 임박한 라이선스가 없습니다.",
                          data={"total": 0}, detail_url=_at("software"))
    return ToolResult(
        summary=f"만료 임박 라이선스 {total}건",
        data={"total": total,
              "items": [{"제품": r.get("product_name") or r.get("name"),
                         "만료일": r.get("expires_at") or r.get("expiry_date"),
                         "수량": r.get("seats") or r.get("quantity")} for r in items]},
        detail_url=_at("software"),
        truncated=cut,
    )


# ─────────────────────────────────────────────────────────────
# 7. 소프트웨어 제품 목록
# ─────────────────────────────────────────────────────────────
@tool(
    name="list_software_products",
    label="소프트웨어 목록 조회",
    description=(
        "사내에서 관리 중인 소프트웨어 제품 목록을 돌려준다. "
        "'우리 무슨 소프트웨어 쓰고 있어', '오피스 라이선스 있어?' 같은 질문에 쓴다."
    ),
    service="it-asset",
)
def list_software_products(user: User) -> ToolResult:
    try:
        rows = _get("/software-products", user=user)
    except Exception as e:  # noqa: BLE001
        return _down(e)

    items, total, cut = _cap(rows)
    if total == 0:
        return ToolResult(summary="등록된 소프트웨어 제품이 없습니다.",
                          data={"total": 0}, detail_url=_at("software"))
    return ToolResult(
        summary=f"소프트웨어 제품 {total}건" + (f" (앞 {len(items)}건만 표시)" if cut else ""),
        data={"total": total,
              "items": [{"제품": r.get("name"), "제조사": r.get("vendor")} for r in items]},
        detail_url=_at("software"),
        truncated=cut,
    )

# ─────────────────────────────────────────────────────────────
# 8. 자리 배치 — 어디 앉는지, 옆에 누가 앉는지
#
# /seats/ 는 자리를 격자(floor · row_idx · col_idx)로 돌려준다.
# 한 자리가 여러 칸을 차지할 수 있어서 row_span · col_span 도 같이 온다.
# "옆에 누구" 는 이 격자에서 맞닿은 칸을 찾는 것이다. 앱에는 그런
# 엔드포인트가 없으므로 포털이 받아서 계산한다.
# ─────────────────────────────────────────────────────────────
def _rect(s: dict) -> tuple[int, int, int, int]:
    """자리가 차지하는 칸 범위 (행시작, 행끝, 열시작, 열끝)."""
    r = int(s.get("row_idx") or 0)
    c = int(s.get("col_idx") or 0)
    return r, r + int(s.get("row_span") or 1) - 1, c, c + int(s.get("col_span") or 1) - 1


def _touching(a: dict, b: dict) -> str | None:
    """b 가 a 의 어느 쪽에 맞닿아 있는가. 안 닿으면 None.

    ※ 여기서 말하는 방향은 **자리 배치 화면(배치도)을 볼 때의 방향**이다.
      사람이 실제로 어느 쪽을 보고 앉는지는 자료에 없다. 책상은 마주 보고
      놓이는 경우가 많아서, 배치도의 '오른쪽'이 앉은 사람에게는 '앞'일 수 있다.
      그래서 '앞·뒤' 라고 부르지 않고 '배치도 위/아래/왼쪽/오른쪽' 으로만 말한다.
      (실제로 이렇게 어긋난 사례가 있었다 — 배치도 오른쪽 사람을 '앞'이라고 답했다)
    """
    if a.get("floor") != b.get("floor"):
        return None
    ar0, ar1, ac0, ac1 = _rect(a)
    br0, br1, bc0, bc1 = _rect(b)
    rows_overlap = ar0 <= br1 and br0 <= ar1
    cols_overlap = ac0 <= bc1 and bc0 <= ac1
    if rows_overlap and bc0 == ac1 + 1:
        return "배치도 오른쪽"
    if rows_overlap and bc1 == ac0 - 1:
        return "배치도 왼쪽"
    if cols_overlap and br0 == ar1 + 1:
        return "배치도 아래"
    if cols_overlap and br1 == ar0 - 1:
        return "배치도 위"
    return None


def _who(s: dict) -> str:
    name = s.get("employee_name")
    if not name:
        return f"(빈자리{' · ' + s['label'] if s.get('label') else ''})"
    bits = [name]
    if s.get("employee_position"):
        bits.append(str(s["employee_position"]))
    return " ".join(bits)


@tool(
    name="find_seat",
    label="자리 배치 조회",
    description=(
        "직원이 어디에 앉는지, 그 주변에 누가 앉는지 알려준다. "
        "'윤예원 어디 앉아?', '윤예원 옆에 누가 앉아?', "
        "'김대리 자리 어디야', '내 옆자리 누구야' 같은 질문에 쓴다. "
        "층·팀·자리 위치와 맞닿은 자리를 함께 돌려준다. "
        "**중요** — 돌려주는 방향은 자리 배치 화면(배치도)을 볼 때의 "
        "위·아래·왼쪽·오른쪽이다. 사람이 어느 쪽을 보고 앉는지는 자료에 없으므로 "
        "'앞에', '뒤에', '마주 보고' 같은 표현으로 바꿔 말하지 말고 "
        "'배치도에서 오른쪽' 처럼 받은 그대로 전달할 것. "
        "같은 이름이 여러 명이면 후보를 먼저 알려준다."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "직원 이름. 일부만 넣어도 찾는다"},
        },
        "required": ["name"],
    },
    service="it-asset",
)
def find_seat(user: User, name: str) -> ToolResult:
    try:
        seats = _get("/seats/", user=user) or []
    except Exception as e:  # noqa: BLE001
        return _down(e)

    hits = [s for s in seats
            if s.get("employee_name") and name.strip() in str(s["employee_name"])]

    if not hits:
        return ToolResult(
            summary=f"'{name}' 님의 자리를 찾지 못했습니다. "
                    "자리 배치에 아직 등록되지 않았거나 이름이 다를 수 있습니다.",
            data={}, detail_url=_at("seats"))

    if len({s["employee_name"] for s in hits}) > 1:
        return ToolResult(
            summary=f"'{name}' 으로 찾은 사람이 여러 명입니다. 누구인지 알려주시면 좁힐 수 있습니다.",
            data={
                  "후보": [{"이름": s.get("employee_name"),
                                  "부서": s.get("employee_department"),
                                  "층": s.get("floor")} for s in hits[:10]]},
            detail_url=_at("seats"))

    me = hits[0]
    around: dict[str, list[str]] = {}
    for s in seats:
        if s is me or s.get("id") == me.get("id"):
            continue
        side = _touching(me, s)
        if side:
            around.setdefault(side, []).append(_who(s))

    where = " · ".join(str(x) for x in
                       (me.get("floor"), me.get("team"), me.get("label")) if x)
    near = "; ".join(f"{k} {', '.join(v)}" for k, v in around.items()) or "맞닿은 자리가 없습니다"
    return ToolResult(
        summary=f"{me.get('employee_name')}({me.get('employee_department')}) — {where} / {near}",
        data={"방향_안내": "위·아래·왼쪽·오른쪽은 자리 배치 화면을 볼 때의 방향입니다. "
                        "실제로 앉은 사람이 어느 쪽을 보는지는 알 수 없으므로 "
                        "'앞/뒤'로 바꿔 말하지 마십시오.",
              "본인": {"이름": me.get("employee_name"),
                     "부서": me.get("employee_department"),
                     "직위": me.get("employee_position"),
                     "층": me.get("floor"), "팀": me.get("team"),
                     "자리": me.get("label"),
                     "내선": me.get("employee_extension")},
              "주변": around},
        detail_url=_at("seats"),
    )


# ─────────────────────────────────────────────────────────────
# 8-2. 층·팀별로 누가 앉는가 — "3층에 직급자 누구야"
#
# find_seat 은 **한 사람**을 찾는 도구다. "3층에 직급자 누구 있어" 처럼
# 범위로 훑는 질문에는 쓸 수 없어서, 모델이 답을 못 하고 되묻기만 했다.
#   "어느 범위를 조회할까요? 직급자 기준을 알려주세요"
#   → 사용자가 답함 → "그런 앱은 없습니다"
# 물어보고 나서 못 한다고 하는 것이 가장 나쁘다. 오가는 만큼 돈도 나간다.
#
# 직급을 여기서 정의하지 않는다. 회사마다 다르고, "직급자"의 경계도
# 사람마다 다르게 본다. 대신 **자료에 있는 직위를 그대로 묶어서** 돌려주고,
# 무엇이 직급자인지는 모델이 답하면서 판단하게 한다.
# ─────────────────────────────────────────────────────────────
@tool(
    name="list_seats",
    label="층·팀별 자리 조회",
    description=(
        "어느 층이나 팀에 누가 앉는지 **한꺼번에** 알려준다. "
        "'3층에 누가 앉아?', '3층 직급자 알려줘', '영업팀 자리 배치 보여줘', "
        "'4층에 팀장 누구야' 처럼 **한 사람이 아니라 범위**를 묻는 질문에 쓴다. "
        "직위(팀장·과장·부장 등)별로 묶어서 돌려주므로, "
        "'직급자'가 누구인지는 돌려받은 직위 목록을 보고 판단하면 된다. "
        "한 사람의 자리나 옆자리를 묻는 것이면 이 도구가 아니라 find_seat 를 쓴다."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "floor": {"type": "string",
                      "description": "층. '3', '3층' 처럼 넣는다. 비우면 전체 층"},
            "team": {"type": "string", "description": "팀·부서 이름 일부"},
            "position": {"type": "string",
                         "description": "직위 일부. 예: 팀장, 과장. 비우면 전부"},
        },
    },
    service="it-asset",
)
def list_seats(user: User, floor: str | None = None, team: str | None = None,
               position: str | None = None) -> ToolResult:
    try:
        seats = _get("/seats/", user=user) or []
    except Exception as e:  # noqa: BLE001
        return _down(e)

    # "3층" 으로 물어도 자료가 "3" 이면 맞춰야 한다. 숫자만 뽑아 비교한다.
    def same_floor(v) -> bool:
        if not floor:
            return True
        want = re.sub(r"\D", "", str(floor)) or str(floor)
        have = re.sub(r"\D", "", str(v or "")) or str(v or "")
        return want == have

    people = []
    for s in seats:
        if not s.get("employee_name"):
            continue                      # 빈자리는 세지 않는다
        if not same_floor(s.get("floor")):
            continue
        if team and team.strip() not in str(s.get("team") or "") \
                and team.strip() not in str(s.get("employee_department") or ""):
            continue
        pos = str(s.get("employee_position") or "").strip()
        if position and position.strip() not in pos:
            continue
        people.append({"이름": s.get("employee_name"),
                       "직위": pos or "(직위 없음)",
                       "부서": s.get("employee_department"),
                       "층": s.get("floor"), "팀": s.get("team"),
                       "자리": s.get("label")})

    # 사용자가 "3층" 이라고 넣었는데 또 "층" 을 붙이면 "3층층" 이 된다
    floor_label = None
    if floor:
        digits = re.sub(r"\D", "", str(floor))
        floor_label = f"{digits}층" if digits else str(floor)
    cond = " · ".join(x for x in (floor_label, team, position) if x) or "전체"
    if not people:
        return ToolResult(
            summary=f"{cond} 조건으로 자리 배치에서 찾은 사람이 없습니다. "
                    "층 번호나 팀 이름이 자료와 다를 수 있습니다.",
            data={"total": 0}, detail_url=_at("seats"))

    # 직위별로 묶는다. 이렇게 줘야 "직급자" 판단을 모델이 할 수 있다.
    by_pos: dict[str, list[str]] = {}
    for p in people:
        who = f"{p['이름']}({p['부서']})" if p["부서"] else p["이름"]
        by_pos.setdefault(p["직위"], []).append(who)

    kinds = ", ".join(f"{k} {len(v)}명" for k, v in
                      sorted(by_pos.items(), key=lambda x: -len(x[1])))

    # 이름 목록은 짧다. 15명까지만 주던 것을 늘렸다 —
    # "3층 팀장 누구야" 에 8명을 다 못 주고 "화면에서 보세요" 하면 쓸모가 없다.
    NAMES_PER_POSITION = 30
    cut = False
    for k, v in list(by_pos.items()):
        if len(v) > NAMES_PER_POSITION:
            by_pos[k] = v[:NAMES_PER_POSITION] + [f"… 외 {len(v) - NAMES_PER_POSITION}명"]
            cut = True

    return ToolResult(
        summary=f"{cond} 자리 배치 — 모두 {len(people)}명 ({kinds})",
        data={"조건": cond, "총원": len(people), "직위별": by_pos,
              "작성지침_이름": "위 직위별 이름은 **그대로 답변에 적어도 됩니다.** "
                        "묻는 직위가 20명 이하면 이름을 다 적으십시오. "
                        "그보다 많을 때만 인원수로 줄이고 화면 링크를 안내하십시오.",
              "작성지침_직급": "'직급자'의 기준은 회사마다 다릅니다. 위 직위 목록에서 "
                        "해당하는 것을 골라 답하고, 어떤 직위를 포함했는지 밝히십시오."},
        detail_url=_at("seats"),
        # 한 직위의 이름이 잘렸을 때만 켠다. 다른 직위는 온전하므로
        # 이것 때문에 답 전체를 감추면 안 된다 (그러면 8명짜리 팀장 목록도 사라진다).
        truncated=cut,
    )


# ─────────────────────────────────────────────────────────────
# 9. IP · 내선 — "김도연 할당 IP 뭐야"
#
# IP 는 사람이 아니라 **자산이나 내선**에 붙는다.
#   PC   → 자산에 IP 배정        (ip_assignments.asset_id)
#   전화 → 내선에 IP 배정        (ip_assignments.extension_id)
# 앱이 employee_name 을 조인해서 같이 내려주므로 이름으로 걸러낼 수 있다.
# ─────────────────────────────────────────────────────────────
@tool(
    name="find_network_info",
    label="IP · 내선 조회",
    description=(
        "직원에게 할당된 IP 주소와 내선번호를 알려준다. "
        "'김도연 IP 뭐야', '김대리 아이피 알려줘', '홍길동 내선번호', "
        "'저 사람 전화번호 몇 번이야' 같은 질문에 쓴다. "
        "IP 는 PC(자산)에 붙은 것과 전화기(내선)에 붙은 것이 따로 있으므로 둘 다 돌려준다. "
        "이름을 안 주면 전체 IP 사용 현황을 요약한다."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string",
                     "description": "직원 이름. 비우면 전체 현황을 요약한다"},
        },
    },
    service="it-asset",
)
def find_network_info(user: User, name: str | None = None) -> ToolResult:
    try:
        ips = _get("/ip-assignments", user=user) or []
        exts = _get("/extensions/", user=user) or []
    except Exception as e:  # noqa: BLE001
        return _down(e)

    if not name:
        used = [x for x in ips if (x.get("status") or "").upper() in ("USED", "IN_USE", "ASSIGNED")]
        return ToolResult(
            summary=f"IP 배정 {len(ips)}건 (사용 중 {len(used)}건), 내선 {len(exts)}건입니다.",
            data={"ip_total": len(ips), "ip_used": len(used), "extension_total": len(exts)},
            detail_url=_at("ips"),
        )

    key = name.strip()
    my_ips = [x for x in ips if key in str(x.get("employee_name") or "")]
    my_exts = [x for x in exts if key in str(x.get("employee_name") or "")]

    if not my_ips and not my_exts:
        return ToolResult(
            summary=f"'{key}' 님에게 배정된 IP 나 내선이 없습니다. "
                    "아직 등록되지 않았거나 이름이 다를 수 있습니다.",
            data={}, detail_url=_at("ips"))

    def one(x):
        # kind 로 PC 인지 전화기인지 구분된다. 어디에 붙은 IP 인지가 중요하다.
        where = x.get("asset_no") or (f"내선 {x['extension_number']}"
                                      if x.get("extension_number") else "")
        return {"IP": x.get("ip_address"), "종류": x.get("kind"),
                "붙은 곳": where, "상태": x.get("status")}

    who = (my_ips or my_exts)[0].get("employee_name") or key
    bits = []
    if my_ips:
        bits.append("IP " + ", ".join(str(x.get("ip_address")) for x in my_ips[:5]))
    if my_exts:
        bits.append("내선 " + ", ".join(str(x.get("number")) for x in my_exts[:5]))
    return ToolResult(
        summary=f"{who} — " + " / ".join(bits),
        data={"이름": who,
              "IP": [one(x) for x in my_ips[:MAX_ROWS]],
              "내선": [{"번호": x.get("number"), "구역": x.get("zone")}
                     for x in my_exts[:MAX_ROWS]]},
        detail_url=_at("ips"),
    )
