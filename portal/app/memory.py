"""기억 기능 — SQLite 기반.

Hermes 의 "영구 기억"이 하는 일과 동일한 원리다.
모델이 학습하는 것이 아니라, 기록을 파일에 쌓아뒀다가
다음 요청 때 프롬프트에 다시 넣어주는 것뿐이다.

두 종류를 저장한다.
  1. 대화 내역(turns)  — 방금 무슨 얘기를 했는지
  2. 사용자 메모(notes) — "나는 IT팀이야" 같은 지속되는 선호
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

DB_PATH = os.environ.get("MEMORY_DB", "./data/memory.db")

# 대화 맥락으로 되살릴 최근 발화 수 (사용자+답변 합계)
HISTORY_LIMIT = int(os.environ.get("HISTORY_LIMIT", "10"))
# 사용자당 메모 상한 — 무한정 쌓이면 프롬프트가 비대해진다
NOTE_LIMIT = int(os.environ.get("NOTE_LIMIT", "20"))

# ── 기록 보관 정책 ───────────────────────────────────────────
#
# 질문·답변 원문을 남긴다. 사내 도구에서는 이 기록이 곧 개선 재료다.
# "직원들이 실제로 뭘 어떻게 묻는가"를 봐야 도구 설명을 고치고,
# 엉뚱한 도구를 부르는 경우를 잡고, 어떤 앱이 더 필요한지 알 수 있다.
#
# 대신 보관 기간을 둔다 (CHAT_LOG_DAYS). 몇 년 뒤까지 남길 이유가 없다.
# 관리자만 볼 수 있고, 화면에서도 관리 이력과 표를 분리해 둔다.
#
#   CHAT_LOG_TEXT=on    기본. 질문·답변 원문까지 남긴다
#   CHAT_LOG_TEXT=off   누가·언제·어떤 기능을 썼는지만 남긴다
#                       (이미 쌓인 원문은 manage.py purge-text 로 지운다)
LOG_TEXT = os.environ.get("CHAT_LOG_TEXT", "on").strip().lower() in ("on", "1", "true", "yes")

# 사용 기록 보관 일수. 0 이면 지우지 않는다.
LOG_DAYS = int(os.environ.get("CHAT_LOG_DAYS", "90"))
# 대화 내역(본인만 열람) 보관 일수. 0 이면 지우지 않는다.
TURN_DAYS = int(os.environ.get("CHAT_KEEP_DAYS", "365"))


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS turns (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_id    TEXT NOT NULL,
            role       TEXT NOT NULL,       -- user | assistant
            content    TEXT NOT NULL,
            links      TEXT NOT NULL DEFAULT '[]',   -- 바로가기 버튼
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, id);

        CREATE TABLE IF NOT EXISTS notes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    TEXT NOT NULL,
            text       TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id);

        CREATE TABLE IF NOT EXISTS audit (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            service    TEXT NOT NULL DEFAULT '',
            user_id    TEXT NOT NULL,
            action     TEXT NOT NULL,
            detail     TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS logs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    TEXT NOT NULL,
            question   TEXT NOT NULL,
            tools      TEXT NOT NULL,
            reply      TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        -- 대화 제목. 첫 문답이 끝나면 한 줄로 요약해서 여기에 넣는다.
        -- 없으면 첫 질문을 잘라서 쓰므로, 이 표가 비어 있어도 화면은 돈다.
        CREATE TABLE IF NOT EXISTS session_titles (
            session_id TEXT PRIMARY KEY,
            user_id    TEXT NOT NULL,
            title      TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)
        # 기존 DB 에 컬럼이 없으면 추가한다
        cols = {r["name"] for r in c.execute("PRAGMA table_info(audit)")}
        if "service" not in cols:
            c.execute("ALTER TABLE audit ADD COLUMN service TEXT NOT NULL DEFAULT ''")
        cols = {r["name"] for r in c.execute("PRAGMA table_info(turns)")}
        if "links" not in cols:
            c.execute("ALTER TABLE turns ADD COLUMN links TEXT NOT NULL DEFAULT '[]'")


def _now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


# ── 대화 내역 ────────────────────────────────────────────────
def save_turn(session_id: str, user_id: str, role: str, content: str,
              links: list[dict] | None = None) -> None:
    """대화 한 줄 저장.

    바로가기 버튼(links)도 함께 남긴다. 답변 텍스트만 저장하면
    나중에 그 대화를 다시 열었을 때 버튼이 사라진다. 답에는
    "리포트 화면에서 확인하세요"라고 적혀 있는데 정작 갈 수 있는
    버튼이 없는 상태가 되어, 답이 잘못된 것처럼 보인다.
    """
    with _conn() as c:
        c.execute(
            "INSERT INTO turns(session_id,user_id,role,content,links,created_at)"
            " VALUES(?,?,?,?,?,?)",
            (session_id, user_id, role, content,
             json.dumps(links or [], ensure_ascii=False), _now()),
        )


def load_history(session_id: str, limit: int = HISTORY_LIMIT) -> list[dict]:
    """최근 대화를 AI 에 넘길 형태로 반환.

    도구 호출 과정은 저장하지 않는다. 최종 발화만 남겨도
    맥락 유지에는 충분하고, 저장 구조가 단순해진다.
    """
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content FROM turns WHERE session_id=?"
            " ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def clear_session(session_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM turns WHERE session_id=?", (session_id,))


# ── 사용자 메모 ──────────────────────────────────────────────
def add_note(user_id: str, text: str) -> bool:
    """상한을 넘으면 저장하지 않고 False 를 반환."""
    with _conn() as c:
        n = c.execute("SELECT COUNT(*) FROM notes WHERE user_id=?", (user_id,)).fetchone()[0]
        if n >= NOTE_LIMIT:
            return False
        c.execute(
            "INSERT INTO notes(user_id,text,created_at) VALUES(?,?,?)",
            (user_id, text, _now()),
        )
    return True


def list_notes(user_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, text FROM notes WHERE user_id=? ORDER BY id", (user_id,)
        ).fetchall()
    return [{"id": r["id"], "text": r["text"]} for r in rows]


def delete_note(user_id: str, note_id: int) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM notes WHERE user_id=? AND id=?", (user_id, note_id))
    return cur.rowcount > 0


def notes_as_prompt(user_id: str) -> str:
    """시스템 프롬프트에 덧붙일 문단. 없으면 빈 문자열."""
    notes = list_notes(user_id)
    if not notes:
        return ""
    lines = "\n".join(f"- {n['text']}" for n in notes)
    return (
        "\n\n[이 사용자에 대해 기억하고 있는 내용]\n"
        f"{lines}\n"
        "위 내용을 참고하되, 사실 확인이 필요한 사항은 반드시 도구로 조회하십시오."
    )


# ── 요청 로그 ────────────────────────────────────────────────
def log_request(user_id: str, question: str, tools: list[str], reply: str) -> None:
    """사용 기록.

    기본값에서는 **질문과 답변 원문을 저장하지 않는다.**
    누가 언제 어떤 기능을 썼는지만 남긴다. 이것만으로도
    "도구를 못 찾는다", "엉뚱한 도구를 부른다" 같은 문제는 대부분 보인다.

    원문이 꼭 필요할 때만 CHAT_LOG_TEXT=on 으로 켠다.
    켜 놓고 잊어버리는 것이 가장 흔한 사고이므로 기본은 off 다.
    """
    q = question[:500] if LOG_TEXT else ""
    r = reply[:2000] if LOG_TEXT else ""
    with _conn() as c:
        c.execute(
            "INSERT INTO logs(user_id,question,tools,reply,created_at)"
            " VALUES(?,?,?,?,?)",
            (user_id, q, ",".join(tools), r, _now()),
        )


def log_action(user_id: str, action: str, detail: str = "", service: str = "") -> None:
    """관리 동작 이력. 누가 무엇을 바꿨는지 남긴다.

    사고가 났을 때 "언제부터 이렇게 됐나"를 추적하는 유일한 수단이다.

    service 는 어느 서비스에서 일어난 일인지. 비우면 포털 자체.
    앱마다 이력이 흩어져 있으면 사고가 났을 때 화면을 여러 개 뒤져야 한다.
    한 곳에 모으되, 서비스로 걸러 볼 수 있게 열을 따로 둔다.
    """
    with _conn() as c:
        c.execute(
            "INSERT INTO audit(service,user_id,action,detail,created_at)"
            " VALUES(?,?,?,?,?)",
            (service, user_id, action, detail, _now()),
        )


def audit_logs(limit: int = 200) -> list[dict]:
    """관리 동작 이력. 누가 설정을 바꿨는지만 담는다.

    예전에는 여기에 챗 질문 원문을 합쳐서 돌려줬는데,
    그러면 관리자 화면이 곧 직원 대화 열람 창이 된다. 분리했다.
    """
    with _conn() as c:
        rows = c.execute(
            "SELECT created_at, service, user_id, action, detail FROM audit"
            " ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def audit_services() -> list[str]:
    """이력에 등장한 서비스 이름. 화면의 필터 목록에 쓴다."""
    with _conn() as c:
        return [r[0] for r in c.execute(
            "SELECT DISTINCT service FROM audit WHERE service<>'' ORDER BY service")]


def audit_actions() -> list[str]:
    """이력에 등장한 동작 이름."""
    with _conn() as c:
        return [r[0] for r in c.execute(
            "SELECT DISTINCT action FROM audit ORDER BY action")]


def usage_logs(limit: int = 200) -> list[dict]:
    """챗 사용 기록. 관리자만 조회한다 (main.py 에서 admin_user 로 막는다).

    질문·답변 원문을 함께 돌려준다. 도구 설명을 고치려면
    "사람들이 실제로 어떻게 묻는지"를 봐야 한다.
    답변은 길어서 앞부분만 자른다. 전체가 필요하면 DB 를 직접 본다.
    """
    with _conn() as c:
        rows = c.execute(
            "SELECT created_at, user_id, tools, question, reply FROM logs"
            " ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [
        {"created_at": r["created_at"], "user_id": r["user_id"],
         "tools": [t for t in (r["tools"] or "").split(",") if t],
         "question": r["question"] or "",
         "reply": (r["reply"] or "")[:600]}
        for r in rows
    ]


def count_user_sessions(user_id: str) -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(DISTINCT session_id) FROM turns"
                         " WHERE user_id=?", (user_id,)).fetchone()[0]


def purge_user(user_id: str, with_audit: bool = False) -> dict:
    """한 사람의 기록을 지운다.

    무엇을 지울지는 **화면에서 고른다.** 기본은 개인 것만이다.

      대화·기억      본인 말고는 아무도 안 본다. 남길 이유가 없다.
      챗 사용 기록   질문 원문이 들어 있다 (관리자만 봄). 개인 것으로 본다.
      관리 이력      "누가 언제 무엇을 바꿨나" 다. 이건 개인 기록이 아니라
                    **회사의 기록**이다. 지우면 설정을 누가 바꿨는지
                    영영 알 수 없다. with_audit 을 켜야 지운다.
    """
    out = {}
    with _conn() as c:
        out["대화"] = c.execute("DELETE FROM turns WHERE user_id=?", (user_id,)).rowcount
        c.execute("DELETE FROM session_titles WHERE user_id=?", (user_id,))
        out["기억"] = c.execute("DELETE FROM notes WHERE user_id=?", (user_id,)).rowcount
        out["챗 기록"] = c.execute("DELETE FROM logs WHERE user_id=?", (user_id,)).rowcount
        if with_audit:
            out["관리 이력"] = c.execute("DELETE FROM audit WHERE user_id=?",
                                     (user_id,)).rowcount
    return out


def purge_old() -> dict:
    """보관 기간이 지난 기록을 지운다. 서버가 뜰 때 한 번 돈다.

    지우지 않으면 몇 년 뒤에 "그때 그 사람이 뭘 물었는지"가
    아무도 필요로 하지 않는데 계속 남아 있게 된다.
    """
    out = {"logs": 0, "turns": 0}
    with _conn() as c:
        if LOG_DAYS > 0:
            out["logs"] = c.execute(
                "DELETE FROM logs WHERE created_at < datetime('now', ?)",
                (f"-{LOG_DAYS} days",)).rowcount
        if TURN_DAYS > 0:
            out["turns"] = c.execute(
                "DELETE FROM turns WHERE created_at < datetime('now', ?)",
                (f"-{TURN_DAYS} days",)).rowcount
        # 대화가 지워졌으면 제목도 남을 이유가 없다
        c.execute("DELETE FROM session_titles WHERE session_id NOT IN"
                  " (SELECT DISTINCT session_id FROM turns)")
    return out


def purge_chat_text() -> int:
    """이미 쌓인 질문·답변 원문만 지운다. 사용 기록 자체는 남긴다.

    원문 저장을 켜 놓고 쓰다가 끄는 경우, 지난 기록은 그대로 남아 있다.
    이 함수로 내용만 비운다.
    """
    with _conn() as c:
        return c.execute(
            "UPDATE logs SET question='', reply=''"
            " WHERE question<>'' OR reply<>''").rowcount


def recent_logs(limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── 대화 제목 ────────────────────────────────────────────────
def get_title(session_id: str) -> str:
    with _conn() as c:
        r = c.execute("SELECT title FROM session_titles WHERE session_id=?",
                      (session_id,)).fetchone()
    return r["title"] if r else ""


def set_title(session_id: str, user_id: str, title: str,
              overwrite: bool = False) -> None:
    """대화 제목을 저장한다.

    overwrite=False 면 이미 있는 제목을 건드리지 않는다 (지난 대화 일괄 처리용).
    overwrite=True 면 덮어쓴다. 대화가 자라면 주제가 달라지기 때문이다.
    좌석을 묻다가 IP 로 넘어간 대화가 "좌석 문의"로만 남으면 안 된다.

    다만 매 발화마다 고치지는 않는다. 언제 다시 지을지는 titles.RETITLE_AT
    이 정한다. 목록이 계속 바뀌면 눈으로 좇기 어려워진다.
    """
    title = (title or "").strip().replace("\n", " ")
    if not title:
        return
    with _conn() as c:
        if overwrite:
            c.execute(
                "INSERT INTO session_titles(session_id,user_id,title,created_at)"
                " VALUES(?,?,?,?)"
                " ON CONFLICT(session_id) DO UPDATE SET title=excluded.title",
                (session_id, user_id, title[:40], _now()),
            )
        else:
            c.execute(
                "INSERT OR IGNORE INTO session_titles(session_id,user_id,title,created_at)"
                " VALUES(?,?,?,?)",
                (session_id, user_id, title[:40], _now()),
            )


def count_user_turns(session_id: str) -> int:
    """이 대화에서 사용자가 몇 번 물었는가. 제목을 다시 지을 시점 판단용."""
    with _conn() as c:
        return c.execute(
            "SELECT COUNT(*) FROM turns WHERE session_id=? AND role='user'",
            (session_id,)).fetchone()[0]


# ── 대화 목록 ────────────────────────────────────────────────
def list_sessions(user_id: str, limit: int = 60) -> list[dict]:
    """이 사용자의 대화 목록. 최근 대화가 위로.

    제목은 요약해 둔 것을 쓰고, 없으면 첫 질문을 잘라서 쓴다.
    (요약 생성이 실패했거나, 예전에 만들어진 대화인 경우)
    """
    with _conn() as c:
        rows = c.execute("""
            SELECT session_id,
                   MAX(id)         AS last_id,
                   MAX(created_at) AS updated_at,
                   COUNT(*)        AS cnt
              FROM turns
             WHERE user_id = ?
          GROUP BY session_id
          ORDER BY updated_at DESC, last_id DESC
             LIMIT ?
        """, (user_id, limit)).fetchall()

        out = []
        for r in rows:
            t = c.execute("SELECT title FROM session_titles WHERE session_id=?",
                          (r["session_id"],)).fetchone()
            title = (t["title"] if t else "").strip()
            titled = bool(title)          # 지어진 제목인가, 첫 질문을 대신 쓴 것인가
            if not title:
                first = c.execute("""
                    SELECT content FROM turns
                     WHERE session_id = ? AND role = 'user'
                  ORDER BY id LIMIT 1
                """, (r["session_id"],)).fetchone()
                title = (first["content"] if first else "새 대화").strip().replace("\n", " ")
            out.append({
                "id": r["session_id"],
                "title": title[:38] + ("…" if len(title) > 38 else ""),
                # 화면이 "제목이 아직 안 지어졌으니 조금 더 기다려 보자"를
                # 판단할 수 있게 알려준다. 없으면 첫 질문과 구분이 안 된다.
                "titled": titled,
                "updated_at": r["updated_at"],
                "count": r["cnt"],
            })
    return out


def sessions_without_title(limit: int = 200) -> list[dict]:
    """제목이 아직 없는 대화들. 첫 문답과 함께 돌려준다.

    manage.py titles 가 쓴다. 제목 기능을 넣기 전에 만들어진 대화는
    첫 질문이 그대로 목록에 보이는데, 그걸 한 줄로 줄여 주기 위한 것이다.
    """
    with _conn() as c:
        sids = c.execute("""
            SELECT session_id, user_id, MIN(id) AS first_id
              FROM turns
             WHERE session_id NOT IN (SELECT session_id FROM session_titles)
          GROUP BY session_id
          ORDER BY first_id DESC
             LIMIT ?
        """, (limit,)).fetchall()

        out = []
        for r in sids:
            rows = c.execute("""
                SELECT role, content FROM turns
                 WHERE session_id = ? ORDER BY id LIMIT 4
            """, (r["session_id"],)).fetchall()
            q = next((x["content"] for x in rows if x["role"] == "user"), "")
            a = next((x["content"] for x in rows if x["role"] == "assistant"), "")
            if not q:
                continue
            out.append({"session_id": r["session_id"], "user_id": r["user_id"],
                        "question": q, "answer": a})
    return out


def load_session(session_id: str, user_id: str) -> list[dict]:
    """대화 전문. 본인 것만 조회 가능 (권한 검증 필수 지점)."""
    with _conn() as c:
        rows = c.execute("""
            SELECT role, content, links, created_at FROM turns
             WHERE session_id = ? AND user_id = ?
          ORDER BY id
        """, (session_id, user_id)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["links"] = json.loads(d["links"] or "[]")
        except json.JSONDecodeError:
            d["links"] = []
        out.append(d)
    return out


def delete_session(session_id: str, user_id: str) -> bool:
    with _conn() as c:
        cur = c.execute(
            "DELETE FROM turns WHERE session_id=? AND user_id=?",
            (session_id, user_id),
        )
        c.execute("DELETE FROM session_titles WHERE session_id=? AND user_id=?",
                  (session_id, user_id))
    return cur.rowcount > 0
