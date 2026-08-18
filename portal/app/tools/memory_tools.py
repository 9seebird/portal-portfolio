"""기억 관련 도구.

사용자가 "기억해둬"라고 하면 저장하고, 다음 대화부터 프롬프트에 반영된다.
Hermes 의 영구 기억과 같은 원리를 최소 구성으로 구현한 것.

주의 — 사용자가 명시적으로 요청했을 때만 저장한다.
AI 가 임의로 판단해 쌓기 시작하면 잘못된 내용이 계속 재사용되고,
왜 그렇게 답했는지 추적하기 어려워진다.
"""

from .. import memory
from ..registry import User, tool
from ..schemas import ToolResult, fail, ok


@tool(
    name="remember_preference",
    label="기억 저장",
    description=(
        "사용자가 앞으로도 기억해 달라고 요청한 내용을 저장한다. "
        "'기억해둬', '앞으로는 ~하게 해줘', '나는 ~부서야', "
        "'매번 ~로 보여줘' 같이 지속적으로 적용할 선호를 말할 때 사용한다. "
        "사용자가 명시적으로 기억을 요청한 경우에만 사용하고, "
        "일반 대화 내용을 임의로 저장하지 않는다. "
        "사실 정보(잔여 연차, 자산 수량 등)는 저장하지 말 것. 그것은 매번 조회해야 한다."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "저장할 내용. 한 문장으로 간결하게 정리해서 전달.",
            }
        },
        "required": ["text"],
    },
)
def remember_preference(user: User, text: str) -> ToolResult:
    text = text.strip()
    if not text:
        return fail("저장할 내용이 없습니다.")
    if len(text) > 200:
        return fail("내용이 너무 깁니다. 한 문장으로 줄여 주세요.")

    if not memory.add_note(user.user_id, text):
        return fail(
            f"기억 항목이 상한({memory.NOTE_LIMIT}개)에 도달했습니다. "
            "기존 항목을 먼저 삭제해 주세요."
        )
    return ok(summary=f"기억했습니다 — {text}", data={"text": text})


@tool(
    name="list_preferences",
    label="기억 조회",
    description=(
        "저장된 기억 내용을 조회한다. "
        "'뭐 기억하고 있어?', '내 설정 보여줘', '기억한 거 알려줘' 등을 물을 때 사용한다."
    ),
    input_schema={"type": "object", "properties": {}},
)
def list_preferences(user: User) -> ToolResult:
    notes = memory.list_notes(user.user_id)
    if not notes:
        return ok(summary="저장된 기억이 없습니다.", data={"notes": []})
    listed = " / ".join(f"{n['id']}. {n['text']}" for n in notes)
    return ok(
        summary=f"{len(notes)}건을 기억하고 있습니다 — {listed}",
        data={"notes": notes},
    )


@tool(
    name="forget_preference",
    label="기억 삭제",
    description=(
        "저장된 기억을 삭제한다. "
        "'그거 잊어줘', '기억 지워줘' 등을 말할 때 사용한다. "
        "어떤 항목인지 불분명하면 먼저 list_preferences 로 목록을 확인하고 "
        "사용자에게 확인한 뒤 삭제한다."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "note_id": {"type": "integer", "description": "삭제할 기억의 번호"}
        },
        "required": ["note_id"],
    },
)
def forget_preference(user: User, note_id: int) -> ToolResult:
    if memory.delete_note(user.user_id, note_id):
        return ok(summary=f"{note_id}번 기억을 삭제했습니다.")
    return fail("해당 번호의 기억을 찾을 수 없습니다.")
