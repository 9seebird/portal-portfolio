"""AI 공급자에 얼마나 썼는지 기록한다.

### 왜 필요한가

포털은 이제 세 군데에서 공급자를 부른다.

    챗      직원이 물을 때마다. 도구를 부르면 한 질문에 두세 번씩 오간다.
    제목    대화 목록에 붙일 제목. 첫 질문·3번째·7번째에 한 번씩.
    그림    사진·스캔 PDF·문서 안에 붙은 캡처를 읽을 때.

이 중 **그림이 특히 눈에 안 띄게 큰다.** 엑셀 한 장을 열면 안에 붙은
캡처 다섯 장이 통째로 넘어간다. 직원은 "파일 하나 올렸을 뿐"이라고
생각하지만 실제로는 이미지 다섯 장 값이 나간다.

지금은 만든 사람 혼자 쓰니 괜찮다. 50명이 쓰기 시작하면 월말에 놀란다.
**놀라기 전에 보이게 해 두는 것**이 이 파일의 목적이다.

### 무엇을 남기나

호출 한 번에 한 줄. 언제·누가·무슨 용도로·어떤 모델을·몇 토큰.
**질문 내용은 남기지 않는다.** 그건 이미 챗 기록(memory.py)이 하는
일이고, 여기서 또 하면 같은 것이 두 곳에 쌓인다.

### 금액

토큰은 정확히 셀 수 있지만 **단가는 계약마다 다르다.** 그래서 여기서
값을 정해 두지 않고, `.env` 에 적어 둔 것이 있으면 그것으로 곱한다.
없으면 토큰 수만 보여준다. 모르는 값을 그럴싸하게 지어내는 것보다
"토큰은 이만큼 썼다"만 정확히 말하는 편이 낫다.

    USAGE_PRICES=openai/gpt-5-mini:350,2800;google/gemini-3.5-flash-lite:140,560

    모델:입력단가,출력단가  —  **100만 토큰당 원(₩)**
    비즈라우터 요금표를 보고 채워 넣으면 된다.

### 실패해도 조용히 넘어간다

기록을 남기다 실패했다고 직원의 질문이 실패하면 안 된다.
이 파일의 모든 쓰기는 예외를 삼킨다.
"""

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
DB_PATH = os.environ.get("MEMORY_DB", "./data/memory.db")

# 몇 달치를 남길지. 오래된 것은 하루 단위 합계만 있어도 되지만,
# 그 정리까지 만들 만큼 양이 많지 않다. 그냥 지운다.
KEEP_DAYS = int(os.environ.get("USAGE_KEEP_DAYS", "180"))

KINDS = ("챗", "제목", "그림")


def _prices() -> dict[str, tuple[float, float]]:
    """모델별 100만 토큰당 단가. (입력, 출력)"""
    out: dict[str, tuple[float, float]] = {}
    raw = os.environ.get("USAGE_PRICES", "").strip()
    for part in raw.split(";"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        model, _, nums = part.rpartition(":")
        bits = [b.strip() for b in nums.split(",")]
        try:
            inp = float(bits[0])
            outp = float(bits[1]) if len(bits) > 1 else inp
        except (ValueError, IndexError):
            log.warning("USAGE_PRICES 를 읽지 못했습니다: %r", part)
            continue
        out[model.strip()] = (inp, outp)
    return out


PRICES = _prices()


def cost(model: str, prompt: int, completion: int) -> float | None:
    """원(₩). 단가를 모르면 None."""
    p = PRICES.get(model)
    if not p:
        return None
    return (prompt * p[0] + completion * p[1]) / 1_000_000


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS ai_usage (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            day        TEXT NOT NULL,      -- 집계용 (KST 기준 날짜)
            user_id    TEXT NOT NULL DEFAULT '',
            kind       TEXT NOT NULL,      -- 챗 / 제목 / 그림
            model      TEXT NOT NULL,
            prompt     INTEGER NOT NULL DEFAULT 0,
            completion INTEGER NOT NULL DEFAULT 0,
            images     INTEGER NOT NULL DEFAULT 0
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_usage_day ON ai_usage(day)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_usage_user ON ai_usage(user_id, day)")


def record(kind: str, model: str, prompt: int = 0, completion: int = 0,
           user_id: str = "", images: int = 0) -> None:
    """한 번 부른 것을 기록한다. 실패하면 조용히 넘어간다."""
    try:
        if not prompt and not completion:
            # 공급자가 사용량을 안 줬다. 0 으로 채운 줄만 쌓이면
            # "썼는데 0" 처럼 보여서 오히려 헷갈린다. 남기지 않는다.
            return
        now = datetime.now(KST)
        with _conn() as c:
            c.execute(
                "INSERT INTO ai_usage(created_at,day,user_id,kind,model,"
                "prompt,completion,images) VALUES(?,?,?,?,?,?,?,?)",
                (now.isoformat(timespec="seconds"), now.strftime("%Y-%m-%d"),
                 user_id or "", kind, model or "?",
                 int(prompt), int(completion), int(images)),
            )
    except Exception:  # noqa: BLE001
        log.debug("사용량 기록 실패", exc_info=True)


def purge_old() -> int:
    if KEEP_DAYS <= 0:
        return 0
    try:
        with _conn() as c:
            cur = c.execute("DELETE FROM ai_usage WHERE day < date('now', ?)",
                            (f"-{KEEP_DAYS} days",))
            return cur.rowcount or 0
    except Exception:  # noqa: BLE001
        return 0


def _rows(sql: str, args: tuple) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(sql, args)]


def _with_cost(rows: list[dict]) -> list[dict]:
    for r in rows:
        r["cost"] = cost(r.get("model", ""), r.get("prompt", 0), r.get("completion", 0))
    return rows


def report(days: int = 30) -> dict:
    """관리자 화면에 넘길 집계.

    나눠 보는 축이 세 개다.
      날짜 — 늘고 있나
      용도 — 어디에 쓰이나 (그림이 갑자기 커지는 것이 여기 보인다)
      사람 — 특정인이 몰아 쓰고 있나
    """
    since = f"-{max(1, days)} days"

    daily = _rows("""
        SELECT day,
               SUM(prompt) AS prompt, SUM(completion) AS completion,
               COUNT(*) AS calls
          FROM ai_usage WHERE day >= date('now', ?)
      GROUP BY day ORDER BY day
    """, (since,))

    # 금액은 모델마다 단가가 달라서, 모델별로 계산해 날짜에 더한다
    by_day_model = _rows("""
        SELECT day, model, SUM(prompt) AS prompt, SUM(completion) AS completion
          FROM ai_usage WHERE day >= date('now', ?)
      GROUP BY day, model
    """, (since,))
    money: dict[str, float] = {}
    known = True
    for r in by_day_model:
        c = cost(r["model"], r["prompt"], r["completion"])
        if c is None:
            known = False
            continue
        money[r["day"]] = money.get(r["day"], 0.0) + c
    for d in daily:
        d["cost"] = round(money.get(d["day"], 0.0)) if PRICES else None

    by_kind = _with_cost(_rows("""
        SELECT kind, model, SUM(prompt) AS prompt, SUM(completion) AS completion,
               SUM(images) AS images, COUNT(*) AS calls
          FROM ai_usage WHERE day >= date('now', ?)
      GROUP BY kind, model ORDER BY (SUM(prompt)+SUM(completion)) DESC
    """, (since,)))

    by_user = _rows("""
        SELECT user_id, SUM(prompt) AS prompt, SUM(completion) AS completion,
               COUNT(*) AS calls
          FROM ai_usage WHERE day >= date('now', ?) AND user_id <> ''
      GROUP BY user_id ORDER BY (SUM(prompt)+SUM(completion)) DESC LIMIT 20
    """, (since,))

    total_p = sum(d["prompt"] for d in daily)
    total_c = sum(d["completion"] for d in daily)
    return {
        "days": days,
        "daily": daily,
        "by_kind": by_kind,
        "by_user": by_user,
        "total": {
            "prompt": total_p,
            "completion": total_c,
            "calls": sum(d["calls"] for d in daily),
            "cost": round(sum(money.values())) if PRICES else None,
        },
        # 단가를 아는 모델과 모르는 모델이 섞여 있으면 금액은 "적어도 이만큼"이다.
        # 그걸 밝히지 않으면 합계를 전부인 줄 안다.
        "priced": bool(PRICES),
        "all_priced": bool(PRICES) and known,
        "prices": {m: list(v) for m, v in PRICES.items()},
    }
