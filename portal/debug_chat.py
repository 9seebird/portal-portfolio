"""대화 1회를 자세히 추적한다.

화면에서 "답을 못 하는" 현상이 생겼을 때 원인을 가리는 용도.
도구가 실제로 무엇을 돌려줬는지, 모델이 몇 번 도구를 불렀는지 그대로 보여준다.

실행:
    python debug_chat.py "이번달 ai 사용량 알려줘"
"""

import json
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

os.environ.setdefault("TOKEN_SALT", "debug")

from app import agent, memory, registry  # noqa: E402
from app.registry import User            # noqa: E402
from app.tools import basic, ai_report, memory_tools, portal  # noqa: E402,F401

memory.init()

LINE = "─" * 62
USER = User("kim", "김대리", dept="인사총무팀", is_admin=True)


def main() -> None:
    q = " ".join(sys.argv[1:]) or "이번달 ai 사용량 알려줘"

    print(LINE)
    print(f"질문: {q}")
    print(f"사용자: {USER.name} / 부서: {USER.dept or '미지정'}"
          f"{' / 관리자' if USER.is_admin else ''}")
    print(f"노출 도구: {', '.join(t['name'] for t in registry.tool_specs(USER))}")
    print(LINE)

    calls = 0
    for ev in agent.chat_stream(user=USER, message=q, session_id=None):
        t = ev.get("type")
        if t == "status":
            print(f"\n[{ev['stage']}] {ev['text']}")
        elif t == "tool_done":
            calls += 1
            mark = "OK " if ev.get("ok") else "실패"
            print(f"  {mark} {ev['label']} ({ev['tool']})")
            if ev.get("summary"):
                print(f"     → {ev['summary']}")
        elif t == "answer":
            print("\n" + LINE)
            print("최종 답변")
            print(LINE)
            print(ev["reply"])
            if ev.get("links"):
                print("\n링크:")
                for l in ev["links"]:
                    print(f"  - {l['url']}")
            print(f"\n도구 호출 {calls}회 · 모델 {ev.get('model')}")
        elif t == "error":
            print(f"\n[오류] {ev['text']}")

    print(LINE)
    if calls >= 4:
        print("도구 호출이 과도합니다. 아래를 점검하세요.")
        print("  1. 도구가 실제 값을 돌려주고 있는가 (위 → 줄 확인)")
        print("  2. 비슷한 도구의 설명이 겹치지 않는가")
        print("  3. 더 큰 모델에서도 같은 현상인지 (.env 의 MODEL 변경)")
    else:
        print("정상 범위입니다.")
    print(LINE)


if __name__ == "__main__":
    main()
