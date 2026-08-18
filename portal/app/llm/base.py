"""공급자 공통 인터페이스.

도구 실행 루프(agent.py)는 이 인터페이스만 사용한다.
따라서 모델·공급자를 바꿔도 루프 코드는 그대로다.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class Completion:
    """공급자 응답을 공통 형태로 정규화한 것."""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    # 다음 요청에 그대로 되돌려 보내야 하는 원본 assistant 메시지
    raw_assistant: Any = None
    # 'stop' | 'length' | 'tool_calls' 등. 빈 답변 원인 진단에 쓴다.
    finish_reason: str = ""
    # 이번 호출에 쓴 토큰 (prompt, completion). 공급자가 안 주면 (0, 0).
    # 비용을 보려면 이게 있어야 한다 (app/usage.py 참고).
    tokens: tuple[int, int] = (0, 0)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class Provider:
    """공급자 구현이 제공해야 하는 것."""

    name: str = "base"
    model: str = ""

    def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
    ) -> Completion:
        """한 번 호출하고 정규화된 응답을 반환."""
        raise NotImplementedError

    def assistant_message(self, c: Completion) -> dict:
        """직전 응답을 대화에 다시 넣을 형태로."""
        raise NotImplementedError

    def tool_result_messages(self, results: list[tuple[ToolCall, dict]]) -> list[dict]:
        """도구 실행 결과를 대화에 넣을 형태로.

        results: [(호출정보, 결과dict), ...]
        """
        raise NotImplementedError
