"""AI 공급자 연결 점검.

포털 전체를 띄우기 전에 이것부터 실행한다.
게이트웨이 주소·키·모델명이 맞는지, 도구 호출이 되는지를 확인한다.

실행:
    python check_llm.py
"""

import json
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

LINE = "─" * 62

PROVIDER = os.environ.get("PROVIDER", "anthropic").lower()
MODEL = os.environ.get("MODEL", "")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "")

# 시험용 도구 하나. 실제 실행은 하지 않고 호출 요청만 확인한다.
TEST_TOOL = {
    "name": "get_server_time",
    "description": (
        "사내 서버의 현재 날짜와 시각을 조회한다. "
        "'지금 몇 시야', '오늘 며칠이야' 등을 물을 때 사용한다."
    ),
    "input_schema": {"type": "object", "properties": {}},
}


def list_models() -> None:
    """게이트웨이가 제공하는 모델 목록 조회 (OpenAI 호환만)."""
    if PROVIDER != "openai":
        print("  (모델 목록 조회는 OpenAI 호환 공급자에서만 지원)")
        return
    try:
        from openai import OpenAI
        c = OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            base_url=BASE_URL or None,
        )
        ids = sorted(m.id for m in c.models.list().data)
        if not ids:
            print("  목록이 비어 있습니다. 게이트웨이 설정을 확인하세요.")
            return
        print(f"  사용 가능 모델 {len(ids)}개:")
        for i in ids:
            mark = "  ← 현재 설정" if i == MODEL else ""
            print(f"    - {i}{mark}")
        if MODEL and MODEL not in ids:
            print(f"\n  ⚠ 설정된 MODEL '{MODEL}' 이 목록에 없습니다. 이름을 확인하세요.")
    except Exception as e:  # noqa: BLE001
        print(f"  모델 목록 조회 실패: {e}")
        print("  (게이트웨이가 /v1/models 를 제공하지 않을 수 있습니다. 무시해도 됩니다.)")


def main() -> None:
    print(LINE)
    print("1. 설정 확인")
    print(LINE)
    print(f"  PROVIDER : {PROVIDER}")
    print(f"  MODEL    : {MODEL or '(미지정 — 기본값 사용)'}")
    if PROVIDER == "openai":
        print(f"  BASE_URL : {BASE_URL or '(미지정 — OpenAI 기본 주소)'}")
        key = os.environ.get("OPENAI_API_KEY", "")
    else:
        key = os.environ.get("ANTHROPIC_API_KEY", "")
    print(f"  API KEY  : {'설정됨 (' + key[:6] + '…)' if key else '없음 ← 먼저 설정하세요'}")

    if not key:
        sys.exit(1)

    print("\n" + LINE)
    print("2. 모델 목록")
    print(LINE)
    list_models()

    print("\n" + LINE)
    print("3. 일반 대화")
    print(LINE)
    from app import llm

    try:
        p = llm.get_provider()
        c = p.complete(
            system="한국어로 짧게 답하십시오.",
            messages=[{"role": "user", "content": "안녕하세요. 한 문장으로 인사해 주세요."}],
            tools=[],
        )
        print(f"  응답: {c.text.strip()[:120]}")
        print("  → 정상")
    except Exception as e:  # noqa: BLE001
        print(f"  실패: {e}")
        print("\n  확인할 것: API 키, BASE_URL, 모델명 철자")
        sys.exit(1)

    print("\n" + LINE)
    print("4. 도구 호출 — 가장 중요")
    print(LINE)
    try:
        c = p.complete(
            system="사내 데이터 관련 질문은 반드시 도구로 확인하십시오.",
            messages=[{"role": "user", "content": "지금 몇 시야?"}],
            tools=[TEST_TOOL],
        )
        if c.wants_tools:
            for call in c.tool_calls:
                print(f"  도구 호출 요청: {call.name}({json.dumps(call.input, ensure_ascii=False)})")
            print("  → 정상. 이 모델로 진행 가능합니다.")
        else:
            print(f"  도구를 부르지 않고 그냥 답했습니다: {c.text.strip()[:120]}")
            print("\n  ⚠ 이 모델은 도구 호출을 지원하지 않거나 판단이 약할 수 있습니다.")
            print("    다른 모델로 바꿔 다시 시험해 보세요.")
            sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"  실패: {e}")
        print("\n  이 모델이 도구 호출(function calling)을 지원하지 않을 수 있습니다.")
        sys.exit(1)

    print("\n" + LINE)
    print("점검 완료. 이제 서버를 띄우세요.")
    print("  uvicorn app.main:app --reload --port 8000")
    print(LINE)


if __name__ == "__main__":
    main()
