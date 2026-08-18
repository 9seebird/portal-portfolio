"""도구 응답 형식.

모든 도구는 ToolResult 를 돌려준다. 형식을 통일해두면
"간단하면 답, 방대하면 링크"를 AI가 일관되게 판단할 수 있다.
"""

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ToolResult:
    # AI 가 그대로 활용할 수 있는 한 줄 요약. 반드시 채울 것.
    summary: str

    # 구조화된 원본 데이터. AI 가 추가 가공할 때 사용.
    data: dict[str, Any] = field(default_factory=dict)

    # 상세 화면 주소. 조건까지 포함된 URL 을 넣으면 바로가기가 된다.
    # 예) https://portal.example.com/ai-report?month=2026-08
    detail_url: str | None = None

    # True 면 결과가 잘렸다는 뜻.
    # AI 에게 "상세는 링크로 안내하라"는 신호가 된다.
    truncated: bool = False

    # 처리 실패 시 사용자에게 보여줄 사유.
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    def for_model(self) -> dict[str, Any]:
        """모델에게 건네는 형태. **주소는 빼고 준다.**

        detail_url 을 그대로 주면 모델이 답변 본문에
        "https://.../ai-report?month=2026-07" 같은 주소를 적는다.
        직원 대부분은 그 주소로 무엇을 해야 하는지 모르고,
        오히려 답이 잘못 나온 것처럼 보인다.

        이동은 화면이 담당한다. 주소는 서버가 따로 들고 있다가
        **바로가기 버튼**으로 그린다. 모델에게는 "상세 화면이 있다"는
        사실만 알려주면 충분하다.

        프롬프트로 "주소를 쓰지 마"라고만 해두면 지킬 때도 있고
        안 지킬 때도 있다. 아예 주지 않는 편이 확실하다.
        """
        d = self.to_dict()

        # 영어 키 이름은 아예 넘기지 않는다.
        # 프롬프트로 "truncated 라고 쓰지 마"라고 해도, 눈앞에 그 낱말이
        # 있으면 모델은 "(도구 결과: truncated = true)" 처럼 옮겨 적는다.
        # 볼 수 없는 말은 옮겨 적을 수도 없다. 대신 우리말 지시로 바꿔 준다.
        notes = []
        if d.pop("detail_url", None):
            notes.append("이 내용을 보여 주는 화면이 따로 있습니다. "
                         "'○○ 화면에서 확인하실 수 있습니다' 정도만 덧붙이십시오. "
                         "이동 버튼은 화면이 알아서 붙입니다.")
        if d.pop("truncated", None):
            notes.append("결과의 일부만 담겨 있습니다. 담긴 것은 그대로 적고, "
                         "나머지는 화면에서 볼 수 있다고만 안내하십시오. "
                         "'잘렸다'거나 '일부만 받았다'는 말 자체는 쓰지 마십시오.")
        if notes:
            d["작성지침_결과"] = " ".join(notes)
        return d


def ok(summary: str, **kwargs) -> ToolResult:
    return ToolResult(summary=summary, **kwargs)


def fail(reason: str) -> ToolResult:
    return ToolResult(summary=reason, error=reason)


def denied(what: str = "이 정보") -> ToolResult:
    """권한 부족. AI 가 우회하지 않도록 명확히 알린다."""
    return ToolResult(
        summary=f"{what}에 접근할 권한이 없습니다.",
        error="permission_denied",
    )
