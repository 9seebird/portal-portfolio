"""도구만 따로 시험하는 스크립트. AI API 를 호출하지 않는다.

엑셀 연결이 제대로 됐는지 먼저 여기서 확인하고,
그 다음에 서버를 띄우는 순서가 효율적이다. API 사용료도 들지 않는다.

실행:
    python test_tools.py
"""

import os

os.environ.setdefault("AI_REPORT_XLSX", "./data/ai_usage.xlsx")
os.environ.setdefault("TOKEN_SALT", "test")

from app import registry, services                       # noqa: E402
from app.registry import User                             # noqa: E402
from app.tools import basic, ai_report, portal            # noqa: E402,F401

# 서비스 목록이 있어야 접근 범위를 판정할 수 있다.
services.init()
services.seed_if_empty()

# 권한 있는 계정 / 없는 계정.
# 권한은 부서로 판정한다. seed 에서 ai-report 는 인사총무팀만 허용해 두었다.
KIM = User("kim", "김대리", dept="인사총무팀")
LEE = User("lee", "이사원", dept="영업팀")

LINE = "─" * 62


def show(title: str, name: str, params: dict, user: User) -> None:
    r = registry.execute(name, params, user)
    print(f"\n▶ {title}")
    print(f"  요약      : {r.summary}")
    if r.detail_url:
        print(f"  링크      : {r.detail_url}")
    if r.truncated:
        print("  잘림 여부 : True  → 목록 대신 링크로 안내됨")
    if r.error:
        print(f"  오류      : {r.error}")
    if r.data:
        keys = ", ".join(list(r.data)[:6])
        print(f"  데이터    : {keys}")


def main() -> None:
    print(LINE)
    print("1. 등록된 도구")
    print(LINE)
    print("  전체        :", ", ".join(registry.all_tool_names()))
    print("  김대리 노출 :", ", ".join(t["name"] for t in registry.tool_specs(KIM)))
    print("  이사원 노출 :", ", ".join(t["name"] for t in registry.tool_specs(LEE)))
    print("\n  → 이사원(영업팀)에게 ai-report 도구가 안 보이면 접근 범위 설정이 정상입니다.")

    print("\n" + LINE)
    print("2. 기본 도구")
    print(LINE)
    show("현재 시각", "get_server_time", {}, KIM)
    show("내 정보", "whoami", {}, KIM)

    print("\n" + LINE)
    print("3. ai-report 도구")
    print(LINE)
    show("이번 달 사용 현황", "get_ai_usage", {}, KIM)
    show("특정 월", "get_ai_usage", {"month": "2026-07"}, KIM)
    show("사용자 지정", "get_ai_usage", {"month": "2026-07", "target_user": "김대리"}, KIM)

    print("\n" + LINE)
    print("4. 권한 차단")
    print(LINE)
    show("권한 없는 계정이 비용 조회", "get_ai_usage", {}, LEE)
    print("\n  → '권한이 없습니다'가 나와야 정상입니다.")

    print("\n" + LINE)
    print("확인 완료. 이제 서버를 띄워 실제 대화를 시험하세요.")
    print("  uvicorn app.main:app --reload --port 8000")
    print(LINE)


if __name__ == "__main__":
    main()
