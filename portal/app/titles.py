"""대화 제목 짓기.

목록에 첫 질문을 그대로 잘라 놓으면 "6월달 ai 사용량 알려줄래?" 처럼
말투까지 남아서 눈에 잘 안 들어온다. 대화를 한 줄로 줄여
"AI 사용량 문의 · 6월" 같은 제목을 붙인다.

### 제목 모양 — 주제 + 대상

    자산 현황 문의 · 사용 중
    좌석·IP 문의 · 김도연
    AI 사용량 문의 · 6월

앞에 **무슨 종류의 문의인지**를 두고, 뒤에 **누구·언제·무엇**을 붙인다.
주제만 쓰면("직원 좌석 문의") 같은 종류를 여러 번 물었을 때 목록에
같은 제목이 줄지어 서로 구분이 안 되고, 물어본 말만 줄이면
("김도연 옆 좌석") 무슨 종류의 일이었는지가 한눈에 안 들어온다.

### 대화가 길어지면 다시 짓는다

첫 문답만 보고 지으면, 좌석을 묻다가 IP 로 넘어간 대화가
"좌석 문의" 로만 남는다. 사용자가 원하는 건 "그 대화가 무엇에 대한
것이었나" 이므로, 대화가 자라면 몇 번 더 고쳐 짓는다.

다만 매 발화마다 고치면 목록이 계속 흔들려서 눈으로 좇기 어렵다.
그래서 **정해진 지점(RETITLE_AT)에서만** 다시 짓는다.

### 두 가지 원칙

1. 답변을 늦추지 않는다 — 별도 스레드에서 만든다.
2. 실패하면 아무 일도 없다 — 제목이 없으면 화면이 첫 질문을 대신 쓴다.
"""

import logging
import os
import re
import threading

from . import llm, memory, usage

log = logging.getLogger(__name__)

# 제목 자동 생성 끄기: CHAT_TITLES=off
ENABLED = os.environ.get("CHAT_TITLES", "on").strip().lower() in ("on", "1", "true", "yes")

MAX_LEN = 28

# 제목을 지을 때 쓸 모델. 비우면 챗과 같은 것을 쓴다.
# 한 줄 받아오는 일이라 싸고 빠른 것이 낫다. 느리면 목록에 제목이 늦게
# 붙어서 "요약이 안 된다"로 보인다.
MODEL = os.environ.get("TITLE_MODEL", "").strip()

# 제목용 토큰 한도. 챗과 나눠 쓰지 않고 따로 준다.
#
# ★ gpt-5 계열은 **생각하는 데도 이 한도를 쓴다.**
#   처음에 600 으로 뒀는데, 그 정도면 「한 줄 제목」에 넉넉하다고 봤기
#   때문이다. 실제로는 생각만 하다 한도를 다 쓰고 빈 문자열이 돌아왔다
#   (finish_reason='length'). 그러면 목록에 「새 대화」가 그대로 남는데,
#   화면에는 아무 오류도 안 뜬다 — 제목은 없어도 되는 것이라 조용히 넘어가게
#   만들어 뒀기 때문이다. 로그를 봐야만 알 수 있었다.
#
#   2000 이면 gpt-5-mini 가 생각을 마치고도 제목을 낸다. 제목은 한 대화에
#   많아야 세 번(1·3·7번째) 짓는 것이라, 한도를 올려도 비용은 거의 안 는다.
#
#   추론하지 않는 모델을 쓰면 이 문제 자체가 없다 — TITLE_MODEL 참고.
MAX_TOKENS = int(os.environ.get("TITLE_MAX_TOKENS", "2000"))

# 사용자 발화가 이 개수가 됐을 때 제목을 **다시** 짓는다.
#
# 첫 제목은 여기 없다. 그건 질문을 받자마자 ensure_first() 가 짓는다.
# 예전에는 1 도 여기 들어 있었는데, 그러면 **답변이 다 끝나야** 제목이
# 붙었다. 답이 20초 걸리는 질문이면 그동안 목록에 「새 대화」가 앉아 있다.
# 첫 제목은 질문 한 줄만 봐도 거의 맞는다 — 답을 기다릴 이유가 없다.
#
# 3·7번째에는 대화 전체를 읽는다. 좌석을 묻다 IP 로 넘어간 대화가
# "좌석 문의" 로만 남는 것을 막으려는 것이고, 그건 답변까지 봐야 안다.
# 촘촘하게 잡으면 목록이 계속 바뀌어서 오히려 찾기 어려워진다.
RETITLE_AT = (3, 7)

PROMPT = (
    "아래는 사내 업무 챗의 대화 내용이다. 대화 목록에 표시할 제목을 하나만 지어라.\n"
    "\n"
    "형식: <주제> 문의 · <대상>\n"
    "  - 앞에는 무슨 종류의 일인지를 쓴다.  예) 자산 현황, 좌석, IP, AI 사용량, 앱 안내\n"
    "  - 뒤에는 누구·언제·무엇인지를 짧게 붙인다.  예) 김도연, 6월, 노트북\n"
    "  - 대상이 딱히 없으면 ' · ' 뒤를 생략하고 주제만 쓴다.\n"
    "\n"
    "규칙:\n"
    "  - 한국어. 전체 24자 이내.\n"
    "  - 대화가 여러 주제를 다뤘으면 가운뎃점으로 묶는다. 예) 좌석·IP 문의 · 김도연\n"
    "  - 질문의 말투(알려줘, ~할까요, 그럼)는 넣지 않는다.\n"
    "  - 따옴표·마침표·설명 없이 제목만 출력한다.\n"
    "\n"
    "예시:\n"
    "  질문 '김도연 옆에 누가 앉아?' + '그럼 김도연 할당 IP가 뭐야'\n"
    "    → 좌석·IP 문의 · 김도연\n"
    "  질문 '현재 사용중인 자산 정리 좀 해줄래'\n"
    "    → 자산 현황 문의 · 사용 중\n"
    "  질문 '6월달 ai 사용량 알려줄래?'\n"
    "    → AI 사용량 문의 · 6월\n"
    "  질문 '이거 내용 분석해 줄 수 있어?' (답변에 'SSD 속도측정' 시트를 읽었다고 나옴)\n"
    "    → 파일 분석 · SSD 속도측정\n"
    "\n"
    "질문만 봐서는 무엇에 대한 것인지 알 수 없을 때가 있다. "
    "('이거 요약해줘', '이거 분석해줘' 처럼 파일을 붙이고 물은 경우) "
    "그럴 때는 **답변에 나온 내용**에서 무엇을 다뤘는지 찾아 제목을 지어라.\n"
)


def _clean(text: str) -> str:
    """모델이 붙인 따옴표·마침표·'제목:' 같은 군더더기를 떼어낸다.

    붙는 순서가 매번 달라서 (".제목." 처럼) 한 번만 떼면 남는다. 변화가
    없을 때까지 돌린다.
    """
    t = (text or "").strip().splitlines()[0] if text else ""
    prev = None
    while t != prev:
        prev = t
        t = t.strip(" .。\"'`「」“”")
        t = re.sub(r"^(제목|title)\s*[:：]\s*", "", t, flags=re.I)
    # 끝에 매달린 가운뎃점 정리 ("좌석 문의 ·" 처럼 대상이 비었을 때)
    t = re.sub(r"\s*[·・]\s*$", "", t)
    return t[:MAX_LEN]


def _ask(convo: str) -> str:
    """모델에게 제목을 하나 받아온다. 실패하면 빈 문자열.

    빈 답이 오면 한 번 더 물어본다. 실패의 대부분은 모델이 생각에
    토큰을 다 쓰고 답을 못 낸 경우인데, 한도를 늘려 다시 물으면 나온다.
    두 번 다 실패하면 **왜 실패했는지를 기록에 남긴다.** 조용히 넘어가면
    나중에 "제목이 왜 안 붙지?" 를 확인할 방법이 없다.
    """
    for attempt, budget in enumerate((MAX_TOKENS, MAX_TOKENS * 2), 1):
        try:
            provider = llm.get_side_provider(MODEL, budget)
            c = provider.complete(
                system=PROMPT,
                messages=[{"role": "user", "content": convo}],
                tools=[],
            )
            usage.record("제목", provider.model, c.tokens[0], c.tokens[1])
            title = _clean(c.text)
            if title:
                return title
            log.warning(
                "대화 제목이 비어서 돌아왔습니다 (%d번째) | 모델=%s 한도=%d 종료이유=%s",
                attempt, provider.model, budget, c.finish_reason or "?",
            )
        except Exception:  # noqa: BLE001
            log.warning("대화 제목 생성 실패 (%d번째)", attempt, exc_info=True)
            return ""
    return ""


def _convo_text(turns: list[dict], budget: int = 1600) -> str:
    """대화를 모델에게 넘길 형태로. 길면 앞부분을 우선한다.

    제목은 "이 대화가 무엇이었나" 이므로 시작 부분이 가장 중요하다.
    뒤쪽이 잘려도 제목의 질은 크게 떨어지지 않는다.
    """
    out, used = [], 0
    for t in turns:
        who = "사용자" if t.get("role") == "user" else "답변"
        line = f"[{who}] {(t.get('content') or '').strip()[:400]}"
        if used + len(line) > budget:
            break
        out.append(line)
        used += len(line)
    return "\n".join(out)


def _make(session_id: str, user_id: str) -> None:
    """지금까지의 대화를 읽어 제목을 짓고 저장한다 (스레드에서 돈다)."""
    try:
        turns = memory.load_session(session_id, user_id)
        if not turns:
            return
        title = _ask(_convo_text(turns))
        if title:
            # 다시 지을 때는 덮어쓴다
            memory.set_title(session_id, user_id, title, overwrite=True)
    except Exception:  # noqa: BLE001
        log.warning("대화 제목 갱신 실패 | session=%s", session_id, exc_info=True)


def ensure(session_id: str, user_id: str, question: str, answer: str) -> None:
    """문답이 끝날 때마다 불린다. 정해진 지점에서만 제목을 (다시) 짓는다.

    question·answer 는 쓰지 않는다. 대화 전체를 다시 읽는 편이
    "이 대화가 무엇이었나" 를 더 정확히 잡는다. 인자는 호출부를
    바꾸지 않으려고 남겨 두었다.
    """
    if not ENABLED or not session_id:
        return
    try:
        n = memory.count_user_turns(session_id)
        if n not in RETITLE_AT:
            return
        if n > 1 and not memory.get_title(session_id):
            # 첫 제목조차 못 만든 대화다. 그래도 한 번 더 시도해 본다.
            pass
    except Exception:  # noqa: BLE001
        return
    threading.Thread(target=_make, args=(session_id, user_id), daemon=True).start()


def ensure_first(session_id: str, user_id: str, question: str) -> None:
    """첫 질문을 받자마자 제목을 짓는다. **답변을 기다리지 않는다.**

    왜 따로 두었나
    ──────────────
    ensure() 는 답이 다 나온 뒤에 불린다. 대화 전체를 읽어야 정확하기
    때문인데, 첫 제목까지 그럴 이유는 없다. 답이 20초 걸리는 질문이면
    그동안 목록에 「새 대화」가 앉아 있고, 사용자 눈에는 고장으로 보인다.
    첫 질문 한 줄이면 "이 대화가 무엇인가" 는 거의 맞는다.

    이미 제목이 있으면 아무것도 하지 않는다 (overwrite=False).
    지난 대화를 이어서 말하는 경우까지 첫 질문으로 되돌리면 안 된다.
    """
    if not ENABLED or not session_id:
        return
    try:
        if memory.get_title(session_id):
            return
        # 이미 오간 말이 있으면 첫 질문이 아니다.
        if memory.count_user_turns(session_id) > 0:
            return
    except Exception:  # noqa: BLE001
        return

    def run():
        try:
            title = _ask(f"[사용자] {question[:600]}")
            if title:
                # overwrite=False — 그 사이 ensure() 가 더 나은 것을
                # 지어 놨다면 그쪽을 남긴다.
                memory.set_title(session_id, user_id, title, overwrite=False)
        except Exception:  # noqa: BLE001
            log.warning("첫 제목 생성 실패 | session=%s", session_id, exc_info=True)

    threading.Thread(target=run, daemon=True).start()


def make_now(question: str, answer: str) -> str:
    """제목을 지금 만들어서 돌려준다 (저장은 하지 않는다).

    ensure() 는 별도 스레드에서 돌지만, 지난 대화를 한꺼번에 처리할 때는
    순서대로 기다려야 하므로 이 함수를 쓴다. manage.py titles 가 부른다.
    """
    return _ask(f"[사용자] {question[:600]}\n[답변] {answer[:600]}")
