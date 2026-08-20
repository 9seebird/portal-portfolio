"""공개 데모용 안전장치.

이 파일은 **공개 저장소에만 있다.** 사내에서 도는 것과 코드가 갈라지지
않도록, 기존 파일은 한 줄도 고치지 않고 여기에만 모아 두었다.
main.py 에 붙는 자리도 두 줄뿐이다 (install(app) · seed()).

DEMO_MODE=0 이면 이 파일의 모든 것이 꺼진다. 그대로 사내에 올려도
평소와 똑같이 돈다.

────────────────────────────────────────────────────────────
왜 필요한가

포트폴리오는 **아무나 들어와서 눌러 보는 곳**이다. 로그인을 열어 둔
이상 다음 세 가지가 실제로 일어난다고 보고 만들어야 한다.

    1. 누군가 관리자 화면에서 계정을 지운다
    2. 누군가 데모 계정 비밀번호를 바꿔 버린다  ← 그 순간 데모가 끝난다
    3. 누군가 챗에 스크립트를 붙여 놓고 잔다    ← 내 카드로 결제된다

「전부 읽기 전용」으로 만들면 셋 다 막히지만, 그러면 볼 게 없다.
엑셀을 올려 계산하고 챗에 물어보는 것이 이 포털의 전부인데 그게 다
막히기 때문이다.

그래서 기준을 하나로 잡았다 — **남는 것만 막는다.**

    막지 않는다   올리기 · 계산 · 챗 · 검색 · 내려받기
                  (요청이 끝나면 사라지는 것들)
    막는다        계정 · 자산 · 서비스 · 부서 · 비밀번호
                  (다음 사람에게 그대로 남는 것들)

────────────────────────────────────────────────────────────
막는 자리를 왜 미들웨어에 두었나

주소마다 `if DEMO_MODE:` 를 넣는 방법도 있다. 28개 주소에 28번
넣어야 하고, 앞으로 주소를 하나 더 만들 때 **빠뜨려도 아무 일도 일어나지
않는다** — 조용히 뚫린 채로 배포된다.

미들웨어는 반대다. 새 주소는 자동으로 검사를 지난다.
빠뜨리려면 일부러 허용 목록에 적어 넣어야 한다.

옆 앱들(자산·매뉴얼 등)은 포털을 거치지 않으므로 여기서 막을 수 없다.
그쪽은 nginx 에서 같은 기준으로 한 번 더 막는다
(`proxy/conf.d/00-demo-guard.conf`). 두 겹인 이유는 서로 놓치는
자리가 다르기 때문이다 — 포털은 자기 주소만, nginx 는 전부.

────────────────────────────────────────────────────────────
만든 사람은 어떻게 고치나

문을 하나 더 냈다. `proxy/conf.d/02-admin.conf` 가 8082 포트에 같은 화면을
띄우는데, 그 입구에는 위의 두 겹이 다 없다. 8082 는 127.0.0.1 로만 열려
있어서 인터넷에서도 사내망에서도 닿지 않는다 — 서버에서는 SSH 터널을
뚫어야 들어온다. 안전장치가 비밀번호가 아니라 **서버 SSH 키**인 셈이라,
비밀번호 하나가 새면 끝나는 구조를 피할 수 있었다.

    ssh -L 8082:127.0.0.1:8082 <계정>@<서버>   →  http://127.0.0.1:8082/
"""

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


def _on(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "on", "yes")


ENABLED = _on("DEMO_MODE")

DEMO_ID = os.environ.get("DEMO_USER_ID", "demo").strip()
DEMO_PW = os.environ.get("DEMO_PASSWORD", "demo1234")

# 챗 한도.
#   하루 · IP 당      한 사람이 눌러 볼 만큼. 20번이면 도구도 몇 개 써 본다.
#   한 달 · 전체 토큰  이건 사람 수와 무관한 **지갑의 한도**다.
#                      IP 는 바꾸면 그만이라, 위쪽만 두면 결국 뚫린다.
CHAT_PER_IP_DAY = int(os.environ.get("DEMO_CHAT_PER_IP_DAY", "20"))
TOKENS_PER_MONTH = int(os.environ.get("DEMO_TOKENS_PER_MONTH", "3000000"))

# ★ 하루치도 따로 막는다.
#   달 한도만 두면, 한 사람이 IP 를 바꿔 가며 하루 만에 다 태울 수 있다.
#   그러면 남은 29일 동안 아무도 챗을 못 쓴다 — 데모가 죽은 것과 같다.
#   하루 한도가 있으면 최악의 날에도 **다음 날 아침에 되살아난다.**
#   기본값은 달 한도의 1/20 이다. 20일은 버틴다는 뜻이고, 하루에 다 태우려면
#   이 값을 넘겨야 하는데 그 순간 그날치만 닫힌다.
TOKENS_PER_DAY = int(os.environ.get("DEMO_TOKENS_PER_DAY",
                                    str(max(1, TOKENS_PER_MONTH // 20))))

DB_PATH = os.environ.get("DEMO_DB", "./data/demo.db")

# 상태를 바꾸는 방법(메서드). GET·HEAD 는 검사하지 않는다.
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}

# 막는 주소. **접두사로 적는다** — /api/admin/ 밑에 무엇이 새로 생기든
# 자동으로 걸린다. 새 관리 주소를 만들 때마다 여기 와서 적어야 한다면
# 언젠가 반드시 빠뜨린다.
BLOCK_PREFIX = (
    "/api/admin/",          # 계정 · 서비스 · 부서 · 권한 — 전부
)
# ★ /api/services/register 는 여기서 막지 않는다.
#   그건 사람이 부르는 주소가 아니라 **앱이 뜰 때 스스로 부르는 주소**다.
#   여기서 막으면 데모를 띄울 때마다 앱들이 목록에 안 나타난다.
#   막아도 되는 이유가 따로 있다 — 이 주소는 nginx 허용 목록에 없어서
#   바깥에서는 애초에 닿지 않고, 컨테이너끼리는 nginx 를 거치지 않는다.
#   (게다가 공유 토큰이 맞아야 받는다)
BLOCK_EXACT = (
    "/api/me/password",     # ★ 이걸 놓치면 데모 계정이 남의 것이 된다
)

DENY_MSG = (
    "체험판에서는 저장되지 않습니다.\n\n"
    "보기 · 엑셀 올려 계산 · 챗 · 검색은 전부 그대로 되지만, "
    "다음 사람에게 남는 것(계정 · 자산 · 서비스 · 비밀번호)만 막아 두었습니다."
)


# ── 챗 횟수 기록 ────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_chat (
    ip   TEXT NOT NULL,
    day  TEXT NOT NULL,
    n    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ip, day)
)"""


def _conn() -> sqlite3.Connection:
    """연결할 때마다 표가 있는지 확인한다.

    ★ 뜰 때 한 번만 만들면 안 된다.
      데이터 폴더는 사람이 지우는 일이 실제로 있다 (자리를 비우려고,
      데모를 처음부터 다시 하려고). 그러면 파일만 새로 생기고 표는 없는
      채로 남아서, **챗을 부를 때마다 500** 이 난다. 화면에는 "알 수 없는
      오류" 만 뜨고 원인은 로그 깊은 곳에 있다.
      만들어 두고 다시 만드는 비용은 마이크로초 단위다. 그 값이면 산다.
    """
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    # ★ commit 까지 해야 한다.
    #   파이썬 sqlite3 는 CREATE TABLE 도 트랜잭션 안에서 돌린다.
    #   commit 없이 연결을 놓으면 되돌아가서, 표는 여전히 없고
    #   바로 다음 줄의 SELECT 가 "no such table" 로 죽는다.
    #   「만들었는데 없다」라 원인을 찾는 데 한참 걸렸다.
    c.execute(_SCHEMA)
    c.commit()
    return c


def init() -> None:
    if not ENABLED:
        return
    with _conn():
        pass


def _chat_count(ip: str, day: str) -> int:
    with _conn() as c:
        r = c.execute("SELECT n FROM demo_chat WHERE ip=? AND day=?",
                      (ip, day)).fetchone()
    return r["n"] if r else 0


def _chat_bump(ip: str, day: str) -> None:
    with _conn() as c:
        c.execute("INSERT INTO demo_chat(ip,day,n) VALUES(?,?,1) "
                  "ON CONFLICT(ip,day) DO UPDATE SET n = n + 1", (ip, day))


def _tokens_since(day_start: str) -> int:
    """그날(또는 그달) 이후로 공급자에 나간 토큰 합.

    따로 세지 않고 usage.py 가 이미 쌓고 있는 것을 읽는다.
    같은 것을 두 곳에서 세면 언젠가 두 숫자가 어긋나고,
    그때 어느 쪽이 맞는지 알 방법이 없다.
    """
    try:
        from . import usage
        with sqlite3.connect(usage.DB_PATH) as c:
            r = c.execute(
                "SELECT COALESCE(SUM(prompt+completion),0) FROM ai_usage "
                "WHERE day >= ?", (day_start,)
            ).fetchone()
        return int(r[0] or 0)
    except Exception:  # noqa: BLE001
        # 셀 수 없으면 **막지 않는다.** 여기서 막아 버리면 기록용 DB 가
        # 잠깐 잠긴 것만으로 데모 전체가 죽는다.
        log.debug("토큰 합계를 읽지 못했습니다", exc_info=True)
        return 0


def status(request: Request | None = None) -> dict:
    """화면에 쓸 값. 로그인 없이도 볼 수 있다.

    비밀번호를 그대로 내보낸다. 어차피 로그인 화면에 적어 둘 값이라
    숨겨 봐야 얻는 것이 없고, 숨기면 README 를 안 읽고 온 사람이
    문 앞에서 돌아간다.
    """
    if not ENABLED:
        return {"demo": False}
    now = datetime.now(KST)
    used = _tokens_since(now.strftime("%Y-%m-01"))
    used_today = _tokens_since(now.strftime("%Y-%m-%d"))
    out = {
        "demo": True,
        "user_id": DEMO_ID,
        "password": DEMO_PW,
        "chat_per_ip_day": CHAT_PER_IP_DAY,
        "tokens_left": max(0, TOKENS_PER_MONTH - used),
        "tokens_left_today": max(0, TOKENS_PER_DAY - used_today),
        "chat_open": used < TOKENS_PER_MONTH and used_today < TOKENS_PER_DAY,
        "notice": DENY_MSG,
    }
    if request is not None:
        from .auth import client_ip
        day = datetime.now(KST).strftime("%Y-%m-%d")
        n = _chat_count(client_ip(request) or "?", day)
        out["chat_left"] = max(0, CHAT_PER_IP_DAY - n)
    return out


# ── 미들웨어 ────────────────────────────────────────────────
def install(app) -> None:
    """main.py 에서 한 줄로 붙인다.  demo.install(app)"""
    if not ENABLED:
        return
    init()

    @app.middleware("http")
    async def _guard(request: Request, call_next):
        path = request.url.path
        method = request.method.upper()

        # ★ 주인 전용 입구로 들어온 요청은 그냥 통과시킨다.
        #
        #   이 헤더는 nginx 가 넣는다(proxy/conf.d/_routes.inc). 공개 입구(80)
        #   에서는 늘 "0" 으로 **덮어써지므로** 브라우저가 직접 넣어도 소용없다.
        #   "1" 이 되려면 8082 로 들어와야 하고, 8082 는 127.0.0.1 로만 열려
        #   있어서 서버에서는 SSH 로 들어온 사람만 닿는다.
        #   즉 안전장치는 비밀번호가 아니라 **서버 SSH 키**다.
        if request.headers.get("x-demo-admin") == "1":
            return await call_next(request)

        if method in UNSAFE:
            if path.startswith(BLOCK_PREFIX) or path in BLOCK_EXACT:
                return JSONResponse(status_code=403, content={"detail": DENY_MSG})

            if path in ("/api/chat", "/api/chat/stream"):
                deny = _chat_gate(request)
                if deny:
                    return JSONResponse(status_code=429, content={"detail": deny})

        return await call_next(request)

    log.info("데모 모드 — 관리 주소 차단 · 챗 IP당 하루 %d회 · "
             "하루 %s토큰 · 월 %s토큰",
             CHAT_PER_IP_DAY, f"{TOKENS_PER_DAY:,}", f"{TOKENS_PER_MONTH:,}")


def _chat_gate(request: Request) -> str | None:
    """막아야 하면 사유를, 통과면 None 을 돌려준다."""
    now = datetime.now(KST)
    if _tokens_since(now.strftime("%Y-%m-%d")) >= TOKENS_PER_DAY:
        return ("오늘 쓸 수 있는 체험용 AI 사용량을 다 썼습니다.\n\n"
                "챗은 내일 다시 열립니다. 다른 앱(자산 · 사업계획 · "
                "휴가)은 그대로 쓰실 수 있습니다.")

    used = _tokens_since(now.strftime("%Y-%m-01"))
    if used >= TOKENS_PER_MONTH:
        return ("이번 달 체험용 AI 사용량을 다 썼습니다.\n\n"
                "챗만 잠시 쉬어 갑니다. 다른 앱(자산 · 사업계획 · "
                "휴가)은 그대로 쓰실 수 있고, 다음 달 1일에 다시 열립니다.")

    from .auth import client_ip
    ip = client_ip(request) or "?"
    day = datetime.now(KST).strftime("%Y-%m-%d")
    n = _chat_count(ip, day)
    if n >= CHAT_PER_IP_DAY:
        return (f"체험판 챗은 하루 {CHAT_PER_IP_DAY}번까지입니다. "
                f"({n}번 쓰셨습니다)\n\n"
                "내일 다시 열립니다. 챗 말고 다른 앱은 제한이 없습니다.")

    # ★ 응답이 아니라 **요청 시점에** 센다.
    #   끝난 뒤에 세면, 오래 걸리는 요청을 한꺼번에 스무 개 던졌을 때
    #   전부 「아직 0번」인 채로 통과한다.
    _chat_bump(ip, day)
    return None


# ── 가짜 명부 ───────────────────────────────────────────────
SEED_FILE = os.environ.get("DEMO_SEED", "./data/demo_seed.json")


def seed_people() -> None:
    """가상 회사 「누리코스메틱」의 직원 명부를 계정으로 만든다.

    관리자 화면의 사용자 명부 · 부서 · 접근 범위 화면은 사람이 없으면
    빈 표만 보인다. 그 화면들이 이 포털에서 제일 손이 많이 간 곳이라,
    비어 있으면 볼 것이 없다.

    비밀번호는 계정마다 임의의 긴 문자열로 둔다. 아무도 이 계정으로
    들어올 수 없어야 한다 — 들어올 수 있는 것은 체험 계정 하나뿐이다.
    """
    import json
    import secrets as _s
    from pathlib import Path

    from . import depts, users
    path = Path(SEED_FILE)
    if not path.exists():
        return
    try:
        people = json.loads(path.read_text(encoding="utf-8")).get("employees", [])
    except Exception:  # noqa: BLE001
        log.warning("%s 를 읽지 못했습니다", path)
        return

    made = 0
    for p in people:
        uid = p.get("email", "").split("@")[0] or p.get("emp_no")
        if not uid or users.get(uid):
            continue
        try:
            users.create(uid, p["name"], _s.token_urlsafe(24),
                         dept=p.get("department", ""), is_admin=False,
                         must_change=False)
            if p.get("status") != "ACTIVE":
                users.set_active(uid, False)
            made += 1
        except Exception:  # noqa: BLE001
            pass
    for name, _size, _floor in _dept_order(people):
        depts.create(name)
    if made:
        log.info("가짜 직원 %d명 만듦", made)


def _dept_order(people) -> list[tuple[str, int, str]]:
    """명부에 나온 순서대로 부서를 모은다 (조직도 순서를 지키려는 것)."""
    seen, out = set(), []
    for p in people:
        d = p.get("department", "")
        if d and d not in seen:
            seen.add(d)
            out.append((d, 0, ""))
    return out


def open_services() -> None:
    """앱들이 등록해 둔 서비스를 열어 준다.

    앱은 뜰 때 포털에 자기를 등록하는데, **중지 상태**로 들어온다.
    누가 볼지 정하고 켜는 것은 사람이 하는 일이기 때문이다.
    사내에서는 그게 맞다. 체험판에서는 켜 줄 사람이 없다.

    앱이 언제 등록할지는 알 수 없어서(포털이 먼저 뜨고 앱이 나중에 뜬다)
    한동안 지켜보다가 새로 들어온 것을 켠다.
    """
    import threading
    import time

    from . import services

    def loop():
        for _ in range(40):          # 5초 간격으로 약 3분
            try:
                for s in services.all_services():
                    if not s["enabled"]:
                        services.update(s["id"], enabled=True, access="all")
                        log.info("체험판 — 서비스 열음: %s", s["id"])
            except Exception:  # noqa: BLE001
                pass
            time.sleep(5)

    threading.Thread(target=loop, daemon=True).start()


# ── 데모 계정 ───────────────────────────────────────────────
def seed() -> None:
    """데모 계정을 만든다. 이미 있으면 비밀번호만 되돌린다.

    되돌리는 이유 — 미들웨어가 /api/me/password 를 막지만,
    막는 코드를 나중에 누가 고칠 수도 있고 나도 실수할 수 있다.
    다시 뜰 때마다 원래대로 돌려 두면 최악의 경우에도 재시작 한 번으로 끝난다.
    """
    if not ENABLED:
        return
    from . import users
    try:
        if users.get(DEMO_ID):
            users.set_password(DEMO_ID, DEMO_PW, must_change=False)
        else:
            users.create(DEMO_ID, "체험 계정", DEMO_PW,
                         dept="인사총무팀", is_admin=True, must_change=False)
        log.info("데모 계정 준비됨 — %s", DEMO_ID)
    except Exception:  # noqa: BLE001
        log.exception("데모 계정을 만들지 못했습니다")

    seed_people()
    open_services()
