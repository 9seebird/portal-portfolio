"""Anthropic (Claude) 공급자."""

import json
import os
from typing import Any

from .base import Completion, Provider, ToolCall


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, model: str, max_tokens: int = 1024):
        from anthropic import Anthropic  # 지연 import — 미사용 시 설치 불요

        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY 가 설정되지 않았습니다. .env 를 확인하세요."
            )
        self.client = Anthropic(api_key=key)
        self.model = model
        self.max_tokens = max_tokens

    def _tools(self, tools: list[dict]) -> list[dict]:
        # 내부 표준 형식이 Anthropic 형식과 동일하므로 그대로 사용
        return tools

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Completion:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            tools=self._tools(tools),
            messages=messages,
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [
            ToolCall(id=b.id, name=b.name, input=dict(b.input))
            for b in resp.content
            if b.type == "tool_use"
        ]
        u = getattr(resp, "usage", None)
        tokens = (getattr(u, "input_tokens", 0) or 0,
                  getattr(u, "output_tokens", 0) or 0) if u else (0, 0)

        return Completion(text=text, tool_calls=calls, raw_assistant=resp.content,
                          finish_reason=resp.stop_reason or "", tokens=tokens)

    def assistant_message(self, c: Completion) -> dict:
        return {"role": "assistant", "content": c.raw_assistant}

    def tool_result_messages(self, results: list[tuple[ToolCall, dict]]) -> list[dict]:
        blocks: list[Any] = [
            {
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": json.dumps(payload, ensure_ascii=False),
            }
            for call, payload in results
        ]
        return [{"role": "user", "content": blocks}]
