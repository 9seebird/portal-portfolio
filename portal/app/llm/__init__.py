"""공급자 선택.

.env 의 PROVIDER 값으로 결정한다.

    PROVIDER=openai      MODEL=gpt-5-nano        ← 저렴. 시험용
    PROVIDER=anthropic   MODEL=claude-haiku-...  ← 저렴
    PROVIDER=anthropic   MODEL=claude-opus-5     ← 고성능. 비쌈

모델을 바꿔도 도구 코드와 실행 루프는 그대로다.
"""

import os

from .base import Completion, Provider, ToolCall  # noqa: F401

_provider: Provider | None = None

# 곁다리 용도(제목 짓기 등)로 만든 공급자. (모델, 한도) 별로 하나씩 둔다.
_side: dict[tuple[str, int], Provider] = {}


def _build(model: str, max_tokens: int) -> Provider:
    kind = os.environ.get("PROVIDER", "anthropic").strip().lower()
    if kind == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(
            model=model or "gpt-5-nano",
            max_tokens=max_tokens,
            base_url=os.environ.get("OPENAI_BASE_URL"),
        )
    if kind == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(model=model or "claude-opus-5", max_tokens=max_tokens)
    raise RuntimeError(
        f"알 수 없는 PROVIDER 값: {kind!r} — 'openai' 또는 'anthropic' 만 지원합니다."
    )


def get_provider() -> Provider:
    """챗이 쓰는 공급자. 최초 사용 시점에 생성한다."""
    global _provider
    if _provider is None:
        _provider = _build(
            os.environ.get("MODEL", "").strip(),
            int(os.environ.get("MAX_TOKENS", "1024")),
        )
    return _provider


def get_side_provider(model: str = "", max_tokens: int = 512) -> Provider:
    """챗 말고 곁다리 일에 쓸 공급자 (제목 짓기 등).

    챗 모델과 **달라도 되는** 일이 있다. 제목 짓기가 그렇다. 한 줄을
    받아오는 데 큰 모델을 쓸 이유가 없고, 느리면 목록에 제목이 늦게
    붙어서 "요약이 안 된다"로 보인다.

    한도(max_tokens)도 따로 준다. gpt-5 계열은 생각하는 데도 이 한도를
    쓰기 때문에, 챗과 같은 값을 나눠 쓰면 제목이 빈 문자열로 돌아오는
    일이 생긴다. 그러면 목록에는 첫 질문이 그대로 남는다.
    """
    key = (model or "", max_tokens)
    if key not in _side:
        _side[key] = _build(model or os.environ.get("MODEL", "").strip(), max_tokens)
    return _side[key]


def reset() -> None:
    """설정을 바꿔 다시 만들 때 사용 (시험용)."""
    global _provider
    _provider = None
    _side.clear()
