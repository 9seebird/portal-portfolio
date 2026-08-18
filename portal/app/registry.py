"""도구 등록소.

@tool 데코레이터로 함수를 등록하면
 1) AI 에게 넘길 도구 목록(JSON 스펙)이 자동 생성되고
 2) AI 가 호출을 요청했을 때 실행까지 연결된다.

도구 함수 시그니처:
    def my_tool(user: User, **params) -> ToolResult
"""

from dataclasses import dataclass
from typing import Any, Callable

from .schemas import ToolResult, denied, fail


@dataclass
class User:
    """요청을 보낸 사용자. 로그인에서 채워진다."""
    user_id: str
    name: str
    dept: str = ""
    is_admin: bool = False
    ip: str | None = None


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., ToolResult]
    service: str | None = None        # 이 도구가 속한 서비스 id
    admin_only: bool = False          # 관리자 전용 도구
    label: str | None = None          # 진행 표시용 한글 이름


_TOOLS: dict[str, Tool] = {}


def tool(
    name: str,
    description: str,
    input_schema: dict[str, Any] | None = None,
    service: str | None = None,
    admin_only: bool = False,
    label: str | None = None,
):
    """도구 등록 데코레이터.

    description 이 정확도를 가장 크게 좌우한다.
    - 무엇을 조회하는지
    - 사용자가 어떤 표현으로 물을 때 쓰는지 (동의어 포함)
    - 언제 쓰면 안 되는지
    까지 적을 것.
    """
    def deco(fn: Callable[..., ToolResult]):
        _TOOLS[name] = Tool(
            name=name,
            description=description,
            input_schema=input_schema or {"type": "object", "properties": {}},
            handler=fn,
            service=service,
            admin_only=admin_only,
            label=label,
        )
        return fn
    return deco


def _allowed(t: Tool, user: User) -> bool:
    """이 사용자가 이 도구를 쓸 수 있는가.

    도구가 서비스에 속해 있으면 그 서비스의 접근 범위를 그대로 따른다.
    권한을 도구마다 따로 정의하지 않는 이유는, 관리자가 포털에서
    접근 범위를 바꾸면 챗에도 즉시 반영되게 하기 위함이다.
    """
    if t.admin_only and not user.is_admin:
        return False
    if not t.service:
        return True                      # 서비스에 속하지 않은 공통 도구

    from . import access, services       # 순환 참조 방지를 위해 지연 import
    svc = services.get(t.service)
    if svc is None:
        return False                     # 서비스가 삭제되면 도구도 잠긴다
    return access.can_use(user, svc, user.ip)


def tool_specs(user: User) -> list[dict[str, Any]]:
    """AI 에게 넘길 도구 목록.

    권한이 없는 도구는 목록에서 아예 제외한다.
    (존재 자체를 감추면 AI 가 시도하지 않으므로 오류 응답이 줄어든다.
     단, 이것은 편의일 뿐 보안 조치가 아니다. 실행 시점에 다시 검사한다.)
    """
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in _TOOLS.values() if _allowed(t, user)
    ]


def execute(name: str, params: dict[str, Any], user: User) -> ToolResult:
    """도구 실행. 권한 검사는 여기서 반드시 다시 한다."""
    t = _TOOLS.get(name)
    if t is None:
        return fail(f"'{name}' 도구를 찾을 수 없습니다.")

    # 목록에서 숨겼더라도 실행 시점에 재검사 (핵심 보안 지점)
    if not _allowed(t, user):
        return denied()

    try:
        return t.handler(user=user, **params)
    except TypeError as e:
        return fail(f"입력값이 올바르지 않습니다: {e}")
    except Exception as e:  # noqa: BLE001
        # 실제 예외 내용을 사용자에게 그대로 노출하지 않는다.
        import logging
        logging.exception("도구 실행 실패: %s", name)
        return fail("처리 중 오류가 발생했습니다. 관리자에게 문의하세요.")


def all_tool_names() -> list[str]:
    return list(_TOOLS.keys())


def tool_services() -> dict[str, str | None]:
    """도구 이름 → 그 도구가 속한 서비스 id.

    관리자 화면의 채팅 이력을 서비스별로 걸러 보는 데 쓴다.
    기록에는 어떤 도구를 썼는지만 남으므로, 그 도구가 어느 앱의
    것인지는 여기서만 알 수 있다. 서비스에 속하지 않은 공통 도구
    (기억하기 같은 것)는 None 이다.
    """
    return {name: t.service for name, t in _TOOLS.items()}


def tool_label(name: str) -> str:
    """진행 표시에 쓸 이름. 없으면 도구 이름 그대로."""
    t = _TOOLS.get(name)
    return (t.label if t and t.label else name)
