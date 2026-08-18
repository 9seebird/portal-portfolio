"""테스트용 기본 도구.

첫 연결 확인은 반드시 권한이 필요 없는 도구로 한다.
권한이 얽히면 "도구 호출이 안 된 것"과 "권한에서 막힌 것"을 구분할 수 없다.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from ..registry import User, tool
from ..schemas import ToolResult, ok

KST = ZoneInfo("Asia/Seoul")


@tool(
    name="get_server_time",
    label="현재 시각 확인",
    description=(
        "사내 서버의 현재 날짜와 시각을 조회한다. "
        "사용자가 '지금 몇 시야', '오늘 며칠이야', '현재 시간', '오늘 날짜' 등을 "
        "물을 때 사용한다. "
        "특정 과거·미래 날짜를 계산할 때의 기준 시각으로도 사용할 수 있다."
    ),
    input_schema={"type": "object", "properties": {}},
)
def get_server_time(user: User) -> ToolResult:
    now = datetime.now(KST)
    return ok(
        summary=now.strftime("%Y년 %m월 %d일 %H시 %M분"),
        data={
            "iso": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M"),
            "weekday": "월화수목금토일"[now.weekday()],
        },
    )


@tool(
    name="whoami",
    label="계정 정보 확인",
    description=(
        "현재 로그인한 사용자 본인의 계정 정보를 조회한다. "
        "'나 누구야', '내 계정', '내 권한' 등을 물을 때 사용한다. "
        "다른 사람의 정보를 조회할 때는 사용할 수 없다."
    ),
    input_schema={"type": "object", "properties": {}},
)
def whoami(user: User) -> ToolResult:
    return ok(
        summary=(f"{user.name}({user.user_id})님으로 로그인되어 있습니다. "
                 f"부서: {user.dept or '미지정'}"
                 f"{' / 관리자' if user.is_admin else ''}"),
        data={"user_id": user.user_id, "name": user.name,
              "dept": user.dept, "is_admin": user.is_admin},
    )
