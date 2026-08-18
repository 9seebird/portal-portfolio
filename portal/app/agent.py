"""도구 실행 루프.

이 파일이 이 프로젝트의 핵심이다. 하는 일은 반복문 하나다.

    1. 사용자 질문 + 도구 목록을 AI 에 전달
    2. AI 응답 확인
         - 일반 답변이면      → 그대로 반환하고 종료
         - 도구 호출 요청이면 → 3번
    3. 해당 도구를 우리 서버에서 실행 (사용자 권한으로)
    4. 결과를 AI 에 다시 전달 → 2번으로

AI 는 판단만 하고, 실제 조회는 전부 우리 서버가 한다.

기억은 여기서 두 방식으로 반영된다.
  - 사용자 메모  → 시스템 프롬프트에 덧붙임
  - 대화 내역    → 이전 발화를 messages 앞에 붙임
"""

import json
import logging
import os

from . import llm, memory, registry, titles, uploads, usage
from .registry import User

log = logging.getLogger(__name__)

MAX_TURNS = int(os.environ.get("MAX_TOOL_TURNS", "5"))


def _save(session_id: str | None, user: User, message: str,
          reply: str, links: list[dict]) -> None:
    """대화를 저장하고, 제목이 없으면 짓게 한다.

    제목 생성은 별도 스레드에서 돌기 때문에 답변이 늦어지지 않는다.
    """
    if not session_id:
        return
    memory.save_turn(session_id, user.user_id, "user", message)
    memory.save_turn(session_id, user.user_id, "assistant", reply, links)
    titles.ensure(session_id, user.user_id, message, reply)


def _with_files(message: str, user: User, file_ids: list[str] | None,
                session_id: str | None = None) -> str:
    """붙인 파일이 있으면 모델에게 알려준다. **내용은 넣지 않는다.**

    포털은 파일을 열어보지 않는다. 모델에게는 "이런 파일이 붙어 있고
    file_id 는 이것" 만 알려주고, 실제 분석은 도구가 그 파일을 앱에
    넘겨서 앱이 한다.

    file_id 를 알려주는 이유는, 도구를 부를 때 모델이 그 값을 넘겨야
    하기 때문이다. 도구는 file_id 로 파일을 꺼내 앱에 전달한다.

    ### 이번 발화만이 아니라 **대화 전체**를 본다

    파일을 붙여 물은 다음 "응 그거 분석해줘" 라고 이어서 말하면 그
    발화에는 첨부가 없다. 이번 것만 보면 파일이 사라지고, 모델은 기억에
    없는 file_id 를 지어내다가 "첨부파일을 찾을 수 없습니다" 를 낸다.

    대화에 저장되는 문장에는 file_id 를 넣지 않기 때문에(이력에 파일
    이름을 남기지 않으려는 것) 모델이 나중에 되찾을 방법이 없다.
    그래서 매 발화마다 **이 대화에 올라온 파일 목록을 다시 만들어** 준다.

    사람은 "아까 그 파일" 이라고 생각한다. 매번 다시 붙일 생각은 하지 않는다.
    """
    ids = list(file_ids or [])
    fresh = set(ids)
    # 이 발화와 함께 **실제로 보낸** 파일만 이 대화에 붙은 것으로 기록한다.
    # 업로드 시점에 기록하면, 골라만 놓고 안 보낸 파일까지 대화에 남는다.
    for fid in ids:
        uploads.attach(fid, session_id or "", user.user_id)
    # 이번에 붙인 것이 맨 앞. 그 뒤는 이 대화에 붙은 순서의 **역순**
    # (최근에 붙인 것이 위로 온다).
    for fid in uploads.session_files(session_id or "", user.user_id):
        if fid not in fresh:
            ids.append(fid)

    files = uploads.describe(ids, user.user_id)
    if not files:
        return message

    lines = []
    for i, f in enumerate(files):
        if f["file_id"] in fresh:
            mark = "  ← 이번 질문에 붙인 파일"
        elif i == 0:
            mark = "  ← 가장 최근에 붙인 파일"
        else:
            mark = "  ← 앞서 이 대화에서 붙인 파일"
        lines.append(f"- {f['name']} ({f['형식']}, {f['크기']}) "
                     f"file_id={f['file_id']}{mark}")

    return (
        f"{message}\n\n"
        "[이 대화에 붙은 파일] — 위에 있을수록 최근입니다\n" + "\n".join(lines) + "\n"
        "이 파일을 다룰 수 있는 도구가 있으면 file_id 를 넘겨서 부르십시오. "
        "file_id 는 **위 목록에 적힌 값을 그대로** 쓰십시오. 지어내지 마십시오.\n"
        "어느 파일을 말하는지 분명하지 않으면 — '이거', '그 파일', 또는 "
        "앞선 답변에 이어지는 질문이면 — **바로 앞 대화에서 다루던 파일**을 씁니다. "
        "그것도 알 수 없으면 목록 맨 위(가장 최근) 파일을 씁니다.\n"
        "다룰 수 있는 도구가 없으면, 파일을 처리할 수 있는 서비스가 아직 "
        "없다고 알리고 IT 담당자에게 문의하도록 안내하십시오. "
        "파일 내용을 짐작해서 답하지 마십시오."
    )


def _rescue(reply: str, summaries: list[str], finish: str) -> str:
    """답변 텍스트가 비어 있을 때 도구 결과로 대신 채운다.

    추론형 모델은 토큰 한도를 추론에 다 써서 본문을 못 내놓는 경우가 있다
    (finish_reason == 'length'). 그때 빈 화면을 보여주는 대신
    도구가 만들어 둔 요약을 그대로 답으로 쓴다.
    """
    if reply and reply.strip():
        return reply
    if summaries:
        if finish == "length":
            log.warning("답변이 비어 도구 요약으로 대체했습니다. MAX_TOKENS 를 늘리세요.")
        return "\n".join(summaries)
    return "요청을 처리하지 못했습니다. 질문을 조금 더 구체적으로 입력해 주세요."

BASE_PROMPT = """당신은 사내 업무 포털의 안내 담당입니다.

원칙:
- 사내 데이터에 관한 질문은 반드시 제공된 도구를 사용해 확인합니다. 추측해서 답하지 않습니다.

- **도구 결과를 그대로 옮겨 붙이지 않습니다.** 도구가 돌려준 것은 당신이 보는
  재료이지 사용자가 볼 글이 아닙니다. 읽고 나서 **사람에게 하는 말로 다시 씁니다.**
  다음 말들은 답변에 절대 나오면 안 됩니다:
    "도구", "도구 결과", "아래는 도구가 반환한", "조회 결과:", "요약:",
    "일부 잘림", "(apps: [])" 처럼 영어 이름과 대괄호·중괄호로 된 원본,
    "작성지침", "결과: 없음".
  키 이름과 값을 그대로 늘어놓지 말고, 항목 이름과 내용만 자연스럽게 적습니다.
- 이름이 "작성지침" 으로 시작하는 항목은 **당신에게 하는 말**입니다.
  시키는 대로 하되 그 문장 자체를 답변에 옮겨 적지 마십시오.
- 결과의 일부만 담겨 온 경우에도 **담긴 것은 그대로 적습니다.** 다 못 받았다는
  이유로 받은 것까지 감추면 안 됩니다. ("팀장 8명은 화면에서 확인하세요" 는
  잘못된 답입니다 — 8명이 손에 있으면 8명을 적어야 합니다.)
  그리고 다 못 받았다는 사실 자체는 굳이 말하지 않습니다.
  "더 자세한 내용은 ○○ 화면에서 보실 수 있습니다" 로 마무리하면 충분합니다.
- 도구가 이름·목록을 돌려줬으면 그것을 답에 적습니다. 20건 이하면 전부 적고,
  그보다 많을 때만 인원수로 줄이고 화면 링크를 함께 안내합니다.
- **주소나 경로를 답변 본문에 적지 않습니다.** /manual/, http://... 같은 것을
  글로 쓰지 마십시오. 이동은 화면 아래 바로가기 버튼으로 제공되므로
  앱 "이름"만 말하면 됩니다. 경로를 보여줘도 대부분 쓰지 못하고,
  오히려 답변이 잘못된 것처럼 보입니다.
- "보여 주는 화면이 따로 있다"고 적혀 오면 "○○ 화면에서 확인하실 수 있습니다"
  정도로만 안내합니다. 버튼은 화면이 알아서 붙입니다.
- error 가 permission_denied 이면 권한이 없다는 사실만 알리고,
  다른 방법으로 우회해서 조회하려 시도하지 않습니다.
- 기본값으로 진행할 수 있으면 되묻지 말고 바로 조회합니다.
  예를 들어 월을 지정하지 않으면 이번 달로, 대상자를 지정하지 않으면 전체로 조회합니다.
- 되묻는 것은 조회 대상이 정말 특정되지 않을 때만 합니다. 확인 질문을 남발하지 않습니다.
- **먼저 도구를 부르고, 그 결과를 보고 말합니다.** 조건을 물어본 다음에
  "그런 기능은 없습니다"라고 답하는 것이 가장 나쁩니다. 사용자는 두 번 대답하고
  아무것도 얻지 못합니다. 할 수 있는지 모르겠으면 일단 가장 가까운 도구를 불러 보고,
  결과가 없거나 맞지 않으면 그때 못 한다고 말합니다.
- 할 수 없는 일이 분명하면 **첫 답에서 바로** 못 한다고 말합니다.
  "범위를 알려주시면 조회하겠습니다" 라고 해 놓고 못 하면 안 됩니다.
- "1) 2) 3) 중 무엇으로 할까요" 처럼 선택지를 늘어놓지 않습니다.
  가장 그럴듯한 것으로 진행하고, 무엇을 기준으로 했는지 한 줄로 밝힙니다.
  사용자가 다른 것을 원하면 그때 말합니다.
- 한 번의 조회로 답할 수 있으면 도구를 여러 번 부르지 않습니다.
- 도구가 "찾지 못했다"고 하면 그대로 전달합니다. 다른 항목이 그 역할을 한다고
  추측하거나, 목록을 대신 제시하며 있는 것처럼 서술하지 않습니다.
- **없는 화면·창구·절차를 지어내지 마십시오.** "고객지원 화면에서 확인하세요",
  "문의 게시판에 남기세요" 처럼 도구가 말하지 않은 곳을 안내하면, 직원은
  있지도 않은 것을 찾아 헤매게 됩니다. 도구 결과에 나온 앱 이름만 말합니다.
  안내할 곳이 없으면 "IT 담당자에게 문의해 주세요" 에서 끝냅니다.
- 붙어 있는 파일에 대해 물으면, 먼저 read_attached_file 로 읽고 그 내용으로 답합니다.
  "무엇을 해드릴까요? 1) 2) 3)" 처럼 선택지를 늘어놓고 되묻지 마십시오.
  읽은 내용을 정리해서 보여주고, 더 필요한 것이 있으면 그때 말하도록 하면 됩니다.
- 도구가 이미 읽어 준 내용을 두고 "이미지는 추출되지 않았습니다", "OCR 을 다시
  시도할까요" 처럼 **하지 않은 일을 제안하지 마십시오.** 도구가 돌려준 것이
  전부이고, 그 안에 "읽은 방법"이 적혀 있습니다. 그대로 믿고 답하면 됩니다.
- file_id 는 [이 대화에 올라온 파일] 목록의 값을 **그대로** 씁니다.
  기억나지 않는다고 지어내지 마십시오. 목록에 없으면 없다고 말합니다.
- 기억은 사용자가 명시적으로 요청했을 때만 저장합니다. 임의로 저장하지 않습니다.
- 잔여 수량·금액처럼 변하는 사실은 기억에 의존하지 말고 매번 도구로 조회합니다.
- 답변은 한국어로, 간결하게 합니다."""


def _system_prompt(user: User) -> str:
    """사용자별 시스템 프롬프트.

    Hermes 의 '영구 기억'과 원리가 같다.
    모델을 바꾸는 것이 아니라 프롬프트에 내용을 덧붙이는 것뿐이다.
    """
    who = (f"\n\n현재 사용자: {user.name}({user.user_id})"
           f", 부서: {user.dept or '미지정'}"
           f"{', 관리자' if user.is_admin else ''}")
    return BASE_PROMPT + who + memory.notes_as_prompt(user.user_id)


def _spent(c, provider, user: User) -> None:
    """이번 호출에 쓴 토큰을 남긴다. 비용을 보려면 이게 있어야 한다.

    도구를 부르면 한 질문에 두세 번 오간다. 그 왕복을 다 세야 실제
    쓴 만큼이 나온다. 그래서 부르는 자리마다 이 한 줄이 붙어 있다.
    """
    usage.record("챗", getattr(provider, "model", ""),
                 c.tokens[0], c.tokens[1], user_id=user.user_id)


def _final_answer(provider, system, messages, user: User) -> str:
    """도구 호출 상한에 도달했을 때, 도구 없이 한 번 더 물어 답을 받는다.

    도구를 못 쓰게 하면 모델은 지금까지 받은 결과로 답할 수밖에 없다.
    "처리하지 못했습니다"로 끝나는 것보다 낫다.
    """
    try:
        c = provider.complete(
            system=system + "\n\n지금까지 조회된 결과만으로 답하십시오. 더 이상 도구를 사용할 수 없습니다.",
            messages=messages,
            tools=[],
        )
        _spent(c, provider, user)
        return c.text
    except Exception:  # noqa: BLE001
        log.exception("최종 답변 생성 실패")
        return ""


def chat(user: User, message: str, session_id: str | None = None,
         file_ids: list[str] | None = None) -> dict:
    """대화 1회 처리.

    session_id 를 넘기면 이전 대화 맥락이 이어진다.
    없으면 단발 질의로 처리한다.
    """
    # 제목은 여기서 시작한다. 답변을 기다리지 않는다.
    # (첫 질문일 때만 실제로 짓는다. 별도 스레드라 여기서 멈추지 않는다)
    titles.ensure_first(session_id, user.user_id, message)

    messages: list[dict] = []
    if session_id:
        messages.extend(memory.load_history(session_id))
    # 모델에게는 첨부 안내가 붙은 문장을 준다.
    # 저장·기록에는 원래 문장만 남긴다 (파일 이름이 이력에 새지 않게).
    messages.append({"role": "user",
                     "content": _with_files(message, user, file_ids, session_id)})

    specs = registry.tool_specs(user)
    system = _system_prompt(user)
    used_tools: list[str] = []
    links: list[dict] = []
    summaries: list[str] = []           # 답변이 비었을 때 대신 쓸 도구 요약

    provider = llm.get_provider()
    seen: dict[str, dict] = {}          # 같은 도구를 같은 값으로 또 부르는 것 방지

    for _ in range(MAX_TURNS):
        c = provider.complete(system=system, messages=messages, tools=specs)
        _spent(c, provider, user)

        # 도구를 부르지 않았다면 최종 답변
        if not c.wants_tools:
            reply = _rescue(c.text, summaries, c.finish_reason)
            _save(session_id, user, message, reply, links)
            memory.log_request(user.user_id, message, used_tools, reply)
            return {
                "reply": reply,
                "links": links,
                "used_tools": used_tools,
                "session_id": session_id,
                "model": f"{provider.name}/{provider.model}",
            }

        messages.append(provider.assistant_message(c))

        results = []
        repeats = 0
        for call in c.tool_calls:
            log.info("도구 호출 | user=%s tool=%s input=%s",
                     user.user_id, call.name, call.input)
            used_tools.append(call.name)

            key = call.name + "|" + json.dumps(call.input, sort_keys=True, ensure_ascii=False)
            if key in seen:
                # 이미 같은 조회를 했다. 다시 실행하지 않고 결과를 되돌려주며 중단을 유도한다.
                payload = dict(seen[key])
                payload["note"] = "이미 조회한 내용입니다. 이 결과로 답변을 작성하십시오."
                results.append((call, payload))
                repeats += 1
                continue

            result = registry.execute(call.name, call.input, user)
            if result.detail_url:
                links.append({"label": result.summary, "url": result.detail_url})

            log.info("도구 결과 | user=%s tool=%s summary=%s",
                     user.user_id, call.name, result.summary)
            payload = result.for_model()
            seen[key] = payload
            if result.error is None:
                summaries.append(result.summary)
            results.append((call, payload))

        messages.extend(provider.tool_result_messages(results))

        # 같은 조회만 반복하고 있다면 더 돌 필요가 없다
        if repeats and repeats == len(c.tool_calls):
            break

    reply = _rescue(_final_answer(provider, system, messages, user), summaries, "")
    _save(session_id, user, message, reply, links)
    memory.log_request(user.user_id, message, used_tools, reply)
    return {
        "reply": reply,
        "links": links,
        "used_tools": used_tools,
        "session_id": session_id,
        "model": f"{provider.name}/{provider.model}",
    }


def chat_stream(user: User, message: str, session_id: str | None = None,
                file_ids: list[str] | None = None):
    """chat() 과 동일하지만 진행 상황을 단계별로 흘려보낸다.

    토큰 단위 스트리밍은 아니다. 도구 호출 전후에 이벤트를 보내
    "무엇을 하는 중인지"를 화면에 표시하기 위한 것이다.
    체감 속도는 이것만으로도 크게 달라진다.
    """
    # 제목은 여기서 시작한다. 답변을 기다리지 않는다.
    # (첫 질문일 때만 실제로 짓는다. 별도 스레드라 여기서 멈추지 않는다)
    titles.ensure_first(session_id, user.user_id, message)

    messages: list[dict] = []
    if session_id:
        messages.extend(memory.load_history(session_id))
    # 모델에게는 첨부 안내가 붙은 문장을 준다.
    # 저장·기록에는 원래 문장만 남긴다 (파일 이름이 이력에 새지 않게).
    messages.append({"role": "user",
                     "content": _with_files(message, user, file_ids, session_id)})

    specs = registry.tool_specs(user)
    system = _system_prompt(user)
    used_tools: list[str] = []
    links: list[dict] = []
    summaries: list[str] = []

    provider = llm.get_provider()
    seen: dict[str, dict] = {}
    yield {"type": "status", "stage": "thinking", "text": "생각하는 중"}

    for _ in range(MAX_TURNS):
        try:
            c = provider.complete(system=system, messages=messages, tools=specs)
        except Exception as e:  # noqa: BLE001
            log.exception("모델 호출 실패")
            yield {"type": "error", "text": f"모델 호출에 실패했습니다: {e}"}
            return
        _spent(c, provider, user)

        if not c.wants_tools:
            reply = _rescue(c.text, summaries, c.finish_reason)
            _save(session_id, user, message, reply, links)
            memory.log_request(user.user_id, message, used_tools, reply)
            yield {
                "type": "answer",
                "reply": reply,
                "links": links,
                "used_tools": used_tools,
                "model": f"{provider.name}/{provider.model}",
            }
            return

        messages.append(provider.assistant_message(c))

        results = []
        repeats = 0
        for call in c.tool_calls:
            label = registry.tool_label(call.name)
            yield {"type": "status", "stage": "tool", "text": f"{label} 중",
                   "tool": call.name}
            used_tools.append(call.name)

            key = call.name + "|" + json.dumps(call.input, sort_keys=True, ensure_ascii=False)
            if key in seen:
                payload = dict(seen[key])
                payload["note"] = "이미 조회한 내용입니다. 이 결과로 답변을 작성하십시오."
                results.append((call, payload))
                repeats += 1
                yield {"type": "tool_done", "tool": call.name, "label": label, "ok": True}
                continue

            result = registry.execute(call.name, call.input, user)
            if result.detail_url:
                links.append({"label": result.summary, "url": result.detail_url})
            log.info("도구 결과 | user=%s tool=%s summary=%s",
                     user.user_id, call.name, result.summary)
            payload = result.for_model()
            seen[key] = payload
            if result.error is None:
                summaries.append(result.summary)
            results.append((call, payload))

            yield {"type": "tool_done", "tool": call.name, "label": label,
                   "ok": result.error is None, "summary": result.summary}

        messages.extend(provider.tool_result_messages(results))
        yield {"type": "status", "stage": "writing", "text": "답변 정리하는 중"}

        if repeats and repeats == len(c.tool_calls):
            break

    yield {"type": "status", "stage": "writing", "text": "답변 정리하는 중"}
    reply = _rescue(_final_answer(provider, system, messages, user), summaries, "")
    _save(session_id, user, message, reply, links)
    memory.log_request(user.user_id, message, used_tools, reply)
    yield {"type": "answer", "reply": reply, "links": links,
           "used_tools": used_tools, "model": f"{provider.name}/{provider.model}"}
