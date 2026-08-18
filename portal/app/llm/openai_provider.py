"""OpenAI 공급자 (Chat Completions).

gpt-5-nano 처럼 저렴한 모델로 시험할 때 사용한다.

주의 — GPT-5 계열은 max_tokens 대신 max_completion_tokens 를 쓴다.
      또한 temperature 등 일부 옵션이 제한되므로 지정하지 않는다.
"""

import json
import logging
import os

from .base import Completion, Provider, ToolCall

log = logging.getLogger(__name__)


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, model: str, max_tokens: int = 1024, base_url: str | None = None):
        from openai import OpenAI  # 지연 import

        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY 가 설정되지 않았습니다. .env 를 확인하세요."
            )
        self.client = OpenAI(api_key=key, base_url=base_url or None)
        self.model = model
        self.max_tokens = max_tokens

    def _tools(self, tools: list[dict]) -> list[dict]:
        """내부 표준 형식 → OpenAI 형식."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ]

    def _token_kwargs(self) -> dict:
        # GPT-5 계열은 max_completion_tokens 만 허용
        m = self.model.lower()
        if m.startswith(("gpt-5", "o1", "o3", "o4")):
            return {"max_completion_tokens": self.max_tokens}
        return {"max_tokens": self.max_tokens}

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Completion:
        msgs = [{"role": "system", "content": system}] + messages
        kwargs = {
            "model": self.model,
            "messages": msgs,
            **self._token_kwargs(),
        }
        if tools:
            kwargs["tools"] = self._tools(tools)

        resp = self.client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        msg = choice.message
        finish = choice.finish_reason or ""

        if finish == "length" and not (msg.tool_calls or msg.content):
            # 추론 토큰이 한도를 다 써서 답변이 나오지 못한 상태.
            # gpt-5 계열에서 MAX_TOKENS 가 작을 때 자주 발생한다.
            log.warning(
                "응답이 토큰 한도에서 잘렸습니다. MAX_TOKENS(%s)를 늘리세요.",
                self.max_tokens,
            )

        calls: list[ToolCall] = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, input=args))

        # 대화에 되돌려 넣을 원본 메시지
        # tool_calls 가 있을 때 content 는 None 이어야 하는 게이트웨이가 있다
        raw = {"role": "assistant", "content": msg.content or (None if msg.tool_calls else "")}
        if msg.tool_calls:
            raw["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]

        u = getattr(resp, "usage", None)
        tokens = (getattr(u, "prompt_tokens", 0) or 0,
                  getattr(u, "completion_tokens", 0) or 0) if u else (0, 0)

        return Completion(text=msg.content or "", tool_calls=calls,
                          raw_assistant=raw, finish_reason=finish, tokens=tokens)

    def assistant_message(self, c: Completion) -> dict:
        return c.raw_assistant

    def tool_result_messages(self, results: list[tuple[ToolCall, dict]]) -> list[dict]:
        # OpenAI 는 도구 결과를 호출 1건당 메시지 1개로 넣는다
        return [
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(payload, ensure_ascii=False),
            }
            for call, payload in results
        ]
