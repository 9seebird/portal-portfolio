"""edu(온라인 교육) 연결 도구.

### 이 도구가 하는 일

포털은 이수 여부를 직접 계산하지 않는다. **edu 에게 물어보고 답을 옮긴다.**

    직원: "나 교육 다 들었어?"
        → 포털이 edu 의 /api/status 를 호출
        → edu 가 자기 진도 기록으로 판정해서 돌려줌
        → 포털은 그걸 한두 문장으로 줄인다

    담당자: "교육 이수율 얼마야"
        → 포털이 edu 의 /api/admin/summary · /api/admin/stats 를 호출
        → 이수율과 아직 안 들은 사람을 돌려줌

### 붙이는 데 필요한 것

`portal/.env` 의 `EDU_API` 하나. 같은 도커 네트워크이므로 컨테이너 이름으로 부른다.

    EDU_API=http://demo-edu:8080

edu 쪽은 고칠 것이 없다. 이미 있는 엔드포인트를 쓴다.

    GET /api/status                     그 사람의 이수 상태
    GET /api/admin/summary              공개 중인 과정들의 이수율
    GET /api/admin/stats?courseId=..    한 과정의 부서별·사람별 현황
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from ..registry import User, tool
from ..schemas import ToolResult, fail

# ── 환경에 맞게 수정할 부분 ──────────────────────────────────
API = os.environ.get("EDU_API", "http://demo-edu:8080").rstrip("/")
EDU_URL = os.environ.get("EDU_URL", "/edu/")
TIMEOUT = float(os.environ.get("EDU_TIMEOUT", "5"))
# 답변에 직접 나열할 최대 인원. 넘으면 링크로 안내한다.
TOP_N = 15
# ────────────────────────────────────────────────────────────

SERVICE_TOKEN = os.environ.get("AUDIT_TOKEN", "")


def _get(path: str, user: User):
    """edu 에 GET. 그 사람으로서 묻는 것이므로 사용자 헤더를 함께 보낸다."""
    headers = {"Accept": "application/json",
               "X-User-Id": user.user_id,
               "X-User-Name": urllib.parse.quote(user.name or ""),
               "X-User-Dept": urllib.parse.quote(user.dept or ""),
               "X-User-Role": "admin" if user.is_admin else "user"}
    if SERVICE_TOKEN:
        headers["X-Service-Token"] = SERVICE_TOKEN
    req = urllib.request.Request(API + path, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


@tool(
    name="get_my_training",
    label="내 교육 이수 확인",
    description=(
        "지금 대화하는 직원 본인의 온라인 교육 이수 상태를 조회한다. "
        "'나 교육 들어야 해?', '교육 다 들었나', '내 교육 남은 거 있어?', "
        "'교육 마감 언제야', '수강 완료됐나' 처럼 **본인의** 교육 진행 상황을 "
        "물을 때 쓴다. 남은 차시와 마감일까지 함께 돌려준다. "
        "※ 전체 이수율이나 다른 사람 현황을 물으면 이 도구가 아니라 "
        "get_training_status 를 쓴다."
    ),
    input_schema={"type": "object", "properties": {}},
    service="edu",
)
def get_my_training(user: User) -> ToolResult:
    """직원 본인의 교육 이수 상태를 알려준다."""
    try:
        d = _get("/api/status", user)
    except urllib.error.HTTPError as e:
        return fail(f"교육 서비스가 응답하지 않습니다. ({e.code})")
    except Exception:
        return fail("교육 서비스에 연결하지 못했습니다.")

    courses = d.get("courses", [])
    if not courses:
        return ToolResult(summary="지금 지정된 교육 과정이 없습니다.")
    left = [c for c in courses if not c["completed"]]
    return ToolResult(
        summary=d.get("summary", ""),
        data={"courses": courses, "남은과정수": len(left)},
        detail_url=EDU_URL if left else None,
    )


@tool(
    name="get_training_status",
    label="교육 이수 현황 조회",
    description=(
        "사내 온라인 교육의 전체 이수 현황을 조회한다. "
        "'교육 이수율 얼마야', '몇 명이나 들었어', '아직 안 들은 사람 누구야', "
        "'미수강자 명단', '부서별 이수율', '교육 진행 상황' 처럼 "
        "**전체 또는 특정 부서의** 현황을 물을 때 쓴다. "
        "과정을 지정하지 않으면 공개 중인 과정 전체의 이수율을 돌려주므로 "
        "사용자에게 되물을 필요가 없다. "
        "인원이 많으면 목록 대신 상세 화면을 안내한다."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "course_id": {"type": "integer",
                          "description": "특정 과정만 볼 때 그 과정 번호. 미지정 시 전체 요약."},
            "only_not_done": {"type": "boolean",
                              "description": "true 면 아직 이수하지 않은 사람만 추린다."},
            "dept": {"type": "string", "description": "특정 부서만 볼 때 부서 이름."},
        },
    },
    service="edu",
    admin_only=True,
)
def get_training_status(user: User, course_id: int | None = None,
                        only_not_done: bool = False, dept: str = "") -> ToolResult:
    """교육 담당자에게 이수율·부서별 현황·미수강자를 알려준다."""
    try:
        if course_id is None:
            s = _get("/api/admin/summary", user)
            if not s.get("courses"):
                return ToolResult(summary="공개 중인 교육 과정이 없습니다.")
            if len(s["courses"]) == 1:
                course_id = s["courses"][0]["id"]
            else:
                return ToolResult(summary=s["summary"],
                                  data={"courses": s["courses"]},
                                  detail_url=EDU_URL + "admin")
        d = _get("/api/admin/stats?courseId=" + str(int(course_id)), user)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return fail("교육 담당자만 볼 수 있는 내용입니다.")
        return fail(f"교육 서비스가 응답하지 않습니다. ({e.code})")
    except Exception:
        return fail("교육 서비스에 연결하지 못했습니다.")

    m, people = d["summary"], d["people"]
    if dept:
        people = [p for p in people if (p.get("dept") or "") == dept]
    if only_not_done:
        people = [p for p in people if not p["completed"]]

    shown = people[:TOP_N]
    course = d["course"]
    when = ""
    if course.get("daysLeft") is not None:
        when = (f", 마감 {course['deadline']} (D-{course['daysLeft']})"
                if course["daysLeft"] >= 0 else f", 마감 {course['deadline']} 지남")
    summary = (f"{course['title']} 이수율 {m['percent']}% — "
               f"대상 {m['total']}명 중 {m['completed']}명 완료, "
               f"{m['inProgress']}명 듣는 중, {m['notStarted']}명 미시작{when}")

    return ToolResult(
        summary=summary,
        data={
            "과정": course["title"],
            "요약": m,
            "부서별": d["byDept"],
            "명단": [{"이름": p.get("name"), "부서": p.get("dept"),
                      "상태": "이수" if p["completed"] else ("듣는 중" if p["started"] else "미시작"),
                      "시청률": f"{p['watchPercent']}%"} for p in shown],
        },
        detail_url=EDU_URL + "admin",
        truncated=len(people) > len(shown),
    )
