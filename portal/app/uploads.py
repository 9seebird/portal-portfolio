"""챗에 올린 파일 보관과 전달.

### 무엇을 하는가

직원이 챗 입력창에 이력서를 붙이면
  1. 포털이 파일을 받아 `data/uploads/` 에 저장하고 file_id 를 준다
  2. 모델에게는 **내용이 아니라 "이런 파일이 붙어 있다"만** 알려준다
  3. 모델이 알맞은 도구를 고르면, 그 도구가 파일을 **앱에 넘긴다**
  4. 앱이 분석해서 돌려준 결과를 포털이 문장으로 옮긴다

포털은 파일을 열어보지 않는다. 이력서를 읽고 점수를 매기는 것은
그 일을 하는 앱의 몫이다. 포털이 직접 파싱하기 시작하면 앱과 포털에
같은 로직이 두 벌 생기고, 새 파일 형식이 생길 때마다 포털을 고쳐야 한다.
(ai-report 에서 엑셀을 두 곳에서 읽다가 숫자가 어긋났던 것과 같은 문제다)

### 보관은 두 곳이 따로 간다

    포털   :  30일 (UPLOAD_KEEP_DAYS). 대화를 다시 열었을 때 무엇을
              올렸는지 보이게 하려는 것뿐이다.
    앱     :  그 앱의 정책대로. 이력서 분석 앱이 이력서를 계속 보관할지는
              그 앱이 정한다. 포털이 지운다고 앱에서 사라지지 않는다.

둘을 헷갈리면 "포털에서 지웠는데 왜 아직 있지?" 가 된다.

### 포털에 남은 사본은 누가 볼 수 있나

    올린 본인          자기가 올린 것만
    지정된 열람자      UPLOAD_VIEWERS 에 적힌 계정만 (기본값: admin)
    그 외 관리자       **못 본다.** is_admin 이어도 열리지 않는다

관리자 권한과 파일 열람을 일부러 분리했다. 서비스·계정을 관리하는 일과
남이 올린 이력서를 들여다보는 일은 다른 문제다. 관리자를 한 명 더
만들었다는 이유로 이력서까지 같이 열리면 안 된다.

앱 쪽 사본은 이 규칙과 무관하다. 이력서 분석 앱의 담당자는 그 앱 화면에서
전부 볼 수 있고, 그건 그 앱의 접근 범위가 정한다.

※ 서버나 DB 에 직접 접근할 수 있는 사람은 언제든 파일을 꺼낼 수 있다.
  이건 어떤 설정으로도 막을 수 없다. 서버 계정 관리로 다뤄야 할 문제다.

### 안전장치

  - 크기 상한 (UPLOAD_MAX_MB)
  - 확장자 허용 목록 (UPLOAD_EXTS)
  - **내용까지 확인한다.** 확장자만 보면 exe 를 pdf 로 바꿔 올릴 수 있다.
  - 본인이 올린 파일만 내려받을 수 있다
"""

import hashlib
import os
import re
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

DB_PATH = os.environ.get("MEMORY_DB", "./data/memory.db")
ROOT = Path(os.environ.get("UPLOAD_DIR", "./data/uploads"))

MAX_MB = float(os.environ.get("UPLOAD_MAX_MB", "20"))
KEEP_DAYS = int(os.environ.get("UPLOAD_KEEP_DAYS", "30"))

# 남이 올린 파일까지 볼 수 있는 계정. 쉼표로 여러 명.
# **is_admin 과 별개다.** 관리자를 늘려도 여기 없으면 못 본다.
VIEWERS = {v.strip() for v in os.environ.get("UPLOAD_VIEWERS", "admin").split(",")
           if v.strip()}

# 직원이 실제로 올릴 만한 것만. 필요해지면 .env 에서 늘린다.
EXTS = {
    e.strip().lower().lstrip(".")
    for e in os.environ.get(
        "UPLOAD_EXTS",
        "pdf,docx,doc,hwp,hwpx,xlsx,xls,csv,txt,md,json,"
        "pptx,ppt,html,htm,png,jpg,jpeg,webp",
    ).split(",")
    if e.strip()
}

# 확장자와 실제 내용이 맞는지 보는 최소한의 확인.
# 완벽한 검사가 아니라, 이름만 바꿔 올린 실행파일을 걸러내는 것이 목적이다.
_MAGIC = {
    "pdf":  [b"%PDF-"],
    # docx·xlsx·pptx·hwpx 는 전부 zip 이다
    "docx": [b"PK\x03\x04"],
    "xlsx": [b"PK\x03\x04"],
    "pptx": [b"PK\x03\x04"],
    "hwpx": [b"PK\x03\x04"],
    # 옛 한글·MS 오피스는 복합 문서 형식
    "hwp":  [b"\xd0\xcf\x11\xe0"],
    "doc":  [b"\xd0\xcf\x11\xe0"],
    "xls":  [b"\xd0\xcf\x11\xe0"],
    "ppt":  [b"\xd0\xcf\x11\xe0"],
    "png":  [b"\x89PNG\r\n"],
    "jpg":  [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    # webp 는 RIFF 컨테이너다. 앞 4바이트 뒤에 크기가 오고 그다음이 "WEBP".
    # 앞부분만 보는 지금 방식으로는 RIFF 까지만 확인한다.
    "webp": [b"RIFF"],
}
# 텍스트류는 시작 바이트가 정해져 있지 않다. 검사하지 않는다.
# html 도 마찬가지다 — <!DOCTYPE 로 시작할 수도, 주석이나 <html 로 시작할 수도 있다.
_NO_MAGIC = {"txt", "csv", "md", "json", "html", "htm"}


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS uploads (
            file_id    TEXT PRIMARY KEY,
            user_id    TEXT NOT NULL,
            session_id TEXT NOT NULL DEFAULT '',
            name       TEXT NOT NULL,      -- 직원이 올린 원래 이름
            ext        TEXT NOT NULL,
            size       INTEGER NOT NULL,
            path       TEXT NOT NULL,      -- 저장 위치 (상대경로)
            sha256     TEXT NOT NULL DEFAULT '',   -- 같은 파일인지 판별용
            created_at TEXT NOT NULL
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_uploads_user ON uploads(user_id)")
        # 이미 만들어진 DB 에는 열이 없다
        cols = {r["name"] for r in c.execute("PRAGMA table_info(uploads)")}
        if "sha256" not in cols:
            c.execute("ALTER TABLE uploads ADD COLUMN sha256 TEXT NOT NULL DEFAULT ''")
        c.execute("CREATE INDEX IF NOT EXISTS idx_uploads_hash ON uploads(user_id, sha256)")
        # 한 번 뽑아낸 글자는 남겨 둔다. 같은 파일을 대화 내내 여러 번
        # 읽게 되는데, 그때마다 그림을 다시 공급자에 보내면 돈이 그만큼 나간다.
        # 파일은 바뀌지 않으므로 다시 뽑을 이유도 없다.
        # 어느 대화에서 **보낸** 파일인지를 따로 기록한다.
        #
        # uploads.session_id 하나로 두면 안 되는 이유가 둘 있다.
        #
        #  ① 같은 파일을 다른 대화에서 다시 올리면 중복으로 걸러져서 처음
        #     기록이 그대로 돌아온다. 그러면 그 파일은 처음 대화에 묶인 채로
        #     남고, 지금 대화에서는 다음 발화부터 사라진다.
        #     ("ssd 속도측정.xlsx 를 올렸는데 왜 배치도 파일을 읽지?")
        #  ② uploads.session_id 는 **올린** 시점의 대화다. 파일을 골라만
        #     놓고 질문은 안 보낸 채 다른 대화로 가는 일이 흔한데, 그것까지
        #     그 대화의 파일로 세면 보낸 적 없는 파일을 읽게 된다.
        #
        # 그래서 "보냈다"는 사실만 여기에 남긴다 (agent 가 기록한다).
        # 파일은 하나여도 보낸 자리는 여럿일 수 있으므로 표를 나눈다.
        #
        # upload_attach 는 이것의 첫 판이었다. 올린 시점을 기준으로 채워서
        # ②를 못 걸렀다. 옮길 만한 내용이 없으므로 버린다.
        c.execute("DROP TABLE IF EXISTS upload_attach")
        c.execute("""
        CREATE TABLE IF NOT EXISTS upload_sent (
            file_id     TEXT NOT NULL,
            session_id  TEXT NOT NULL,
            user_id     TEXT NOT NULL,
            sent_at     TEXT NOT NULL,
            PRIMARY KEY (file_id, session_id)
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_sent_session"
                  " ON upload_sent(session_id, user_id, sent_at DESC)")
        c.execute("""
        CREATE TABLE IF NOT EXISTS upload_text (
            file_id    TEXT PRIMARY KEY,
            how        TEXT NOT NULL,      -- 글자 / 그림 / 글자+그림
            text       TEXT NOT NULL,
            cut        INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )""")


def _now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _safe_name(name: str) -> str:
    """원래 이름은 보여주기용으로만 쓴다. 경로로는 절대 쓰지 않는다.

    "../../etc/passwd" 같은 이름이 그대로 경로가 되면 큰일이다.
    실제 저장 이름은 무작위 file_id 로 만든다.
    """
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f]", "", name).strip()
    return name[:120] or "이름없는파일"


class UploadError(Exception):
    """직원에게 그대로 보여줄 수 있는 거절 사유."""


def find_same(user_id: str, digest: str) -> dict | None:
    """이 사람이 **같은 내용**의 파일을 이미 올렸는가.

    이름이 아니라 내용(sha256)으로 본다. "이력서.pdf" 와 "이력서_최종.pdf"
    가 같은 파일일 수도 있고, 이름이 같아도 다른 파일일 수도 있다.
    """
    if not digest:
        return None
    with _conn() as c:
        r = c.execute(
            "SELECT * FROM uploads WHERE user_id=? AND sha256=?"
            " ORDER BY created_at DESC LIMIT 1",
            (user_id, digest),
        ).fetchone()
    if not r:
        return None
    meta = dict(r)
    # 기록은 남아 있는데 파일이 지워진 경우가 있다 (보관 기간 정리 등)
    return meta if (ROOT / meta["path"]).exists() else None


def save(user_id: str, session_id: str, filename: str, blob: bytes) -> dict:
    """파일을 받아 저장하고 정보를 돌려준다. 문제가 있으면 UploadError.

    이미 올린 것과 **내용이 같으면** 새로 저장하지 않고 그때 것을 돌려준다.
    같은 파일을 여러 번 끌어다 놓아도 하나로 취급된다.
    """
    name = _safe_name(filename)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""

    if not ext or ext not in EXTS:
        raise UploadError(
            f"'{ext or '확장자 없음'}' 형식은 올릴 수 없습니다. "
            f"가능한 형식: {', '.join(sorted(EXTS))}"
        )

    size = len(blob)
    if size == 0:
        raise UploadError("빈 파일입니다.")
    if size > MAX_MB * 1024 * 1024:
        raise UploadError(f"파일이 너무 큽니다. {MAX_MB:g}MB 까지 올릴 수 있습니다.")

    # 확장자만 믿지 않는다
    if ext not in _NO_MAGIC:
        heads = _MAGIC.get(ext)
        if heads and not any(blob.startswith(h) for h in heads):
            raise UploadError(
                f"파일 내용이 {ext} 형식이 아닙니다. "
                "확장자만 바꾼 파일은 올릴 수 없습니다."
            )

    # 내용이 같은 파일을 또 올렸으면 그때 것을 그대로 쓴다.
    # 디스크도 아끼고, 화면에도 같은 칩이 두 개 뜨지 않는다.
    digest = hashlib.sha256(blob).hexdigest()
    same = find_same(user_id, digest)
    if same:
        return {"file_id": same["file_id"], "name": same["name"],
                "ext": same["ext"], "size": same["size"], "duplicate": True}

    file_id = secrets.token_urlsafe(16)
    sub = datetime.now(KST).strftime("%Y%m")
    (ROOT / sub).mkdir(parents=True, exist_ok=True)
    rel = f"{sub}/{file_id}.{ext}"
    (ROOT / rel).write_bytes(blob)

    with _conn() as c:
        c.execute(
            "INSERT INTO uploads(file_id,user_id,session_id,name,ext,size,path,sha256,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (file_id, user_id, session_id, name, ext, size, rel, digest, _now()),
        )
    return {"file_id": file_id, "name": name, "ext": ext, "size": size,
            "duplicate": False}


def attach(file_id: str, session_id: str, user_id: str) -> None:
    """이 파일이 이 대화에 붙었다고 기록한다 (같은 자리에 또 붙이면 시각만 갱신).

    ### 올린 때가 아니라 **보낸 때** 기록한다

    파일을 골라 놓기만 하고 질문을 안 보낸 채 다른 대화로 가 버리는 일이
    흔하다. 그때 올린 것만으로 그 대화에 묶어 버리면, 나중에 돌아와서
    "지금 올린 파일 읽혀?" 라고 물었을 때 **보낸 적도 없는 파일**을 읽는다.

    파일이 대화의 일부가 되는 시점은 그 파일을 **붙여서 질문을 보낸** 때다.
    그래서 이 함수는 업로드가 아니라 agent 가 부른다.
    """
    if not session_id:
        return
    with _conn() as c:
        c.execute(
            "INSERT INTO upload_sent(file_id,session_id,user_id,sent_at)"
            " VALUES(?,?,?,?)"
            " ON CONFLICT(file_id,session_id) DO UPDATE SET sent_at=excluded.sent_at",
            (file_id, session_id, user_id, _now()),
        )


def may_view(meta: dict, user_id: str) -> bool:
    """이 사람이 이 파일을 열어도 되는가.

    올린 본인이거나, UPLOAD_VIEWERS 에 적힌 계정이어야 한다.
    관리자(is_admin)라는 이유만으로는 열리지 않는다 — 일부러 그렇게 뒀다.
    """
    return meta["user_id"] == user_id or user_id in VIEWERS


def get(file_id: str, user_id: str) -> dict | None:
    """열람 권한이 있을 때만 돌려준다.

    남의 file_id 를 주소창에 찍어 넣어도 열리지 않는다.
    """
    with _conn() as c:
        r = c.execute("SELECT * FROM uploads WHERE file_id=?", (file_id,)).fetchone()
    if not r:
        return None
    meta = dict(r)
    return meta if may_view(meta, user_id) else None


def read(file_id: str, user_id: str) -> tuple[dict, bytes] | None:
    meta = get(file_id, user_id)
    if not meta:
        return None
    p = ROOT / meta["path"]
    if not p.exists():
        return None
    return meta, p.read_bytes()


def get_text(file_id: str) -> tuple[str, str, bool] | None:
    """전에 뽑아 둔 글자. (글자, 어떻게 읽었는지, 잘렸는지) 또는 None."""
    with _conn() as c:
        r = c.execute("SELECT how,text,cut FROM upload_text WHERE file_id=?",
                      (file_id,)).fetchone()
    return (r["text"], r["how"], bool(r["cut"])) if r else None


def put_text(file_id: str, text: str, how: str, cut: bool) -> None:
    """뽑아낸 글자를 남겨 둔다. 실패해도 그냥 넘어간다 (없어도 되는 것)."""
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO upload_text(file_id,how,text,cut,created_at)"
                " VALUES(?,?,?,?,?)"
                " ON CONFLICT(file_id) DO UPDATE SET"
                "  how=excluded.how, text=excluded.text, cut=excluded.cut,"
                "  created_at=excluded.created_at",
                (file_id, how, text, 1 if cut else 0, _now()),
            )
    except Exception:  # noqa: BLE001
        pass


def recent(limit: int = 100) -> list[dict]:
    """올라온 파일 목록. **열람자 확인은 부르는 쪽에서 한다.**"""
    with _conn() as c:
        rows = c.execute(
            "SELECT file_id,user_id,name,ext,size,created_at FROM uploads"
            " ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def session_files(session_id: str, user_id: str, limit: int = 5) -> list[str]:
    """이 대화에서 이 사람이 **붙여서 보낸** 파일들 (최근 것부터).

    **왜 필요한가** — 파일을 붙여서 물으면 그 다음 질문("응 그거 분석해줘")
    에는 첨부가 없다. 그때 파일이 사라져 버리면 "첨부파일을 찾을 수 없습니다"
    가 되고, 사용자는 같은 파일을 계속 다시 올려야 한다.

    사람은 "아까 그 파일" 이라고 생각하지, 매번 다시 붙일 생각을 하지 않는다.
    그래서 **대화 단위로** 기억한다.

    올리기만 하고 보내지 않은 것은 여기 없다. 그건 아직 이 대화의 일부가
    아니다 (attach 의 설명 참고).
    """
    if not session_id:
        return []
    with _conn() as c:
        rows = c.execute(
            "SELECT file_id FROM upload_sent WHERE session_id=? AND user_id=?"
            " ORDER BY sent_at DESC, rowid DESC LIMIT ?",
            (session_id, user_id, limit),
        ).fetchall()
    return [r["file_id"] for r in rows]


def describe(file_ids: list[str], user_id: str) -> list[dict]:
    """모델에게 알려줄 첨부 목록. **내용은 넣지 않는다.**

    본인이 올린 것만 넣는다. 열람자 권한으로 남의 파일을 챗에 끌어오는
    길을 열어두지 않는다 — 그건 화면에서 확인할 일이지 챗이 할 일이 아니다.
    """
    out = []
    for fid in file_ids or []:
        m = get(fid, user_id)
        if m and m["user_id"] == user_id:
            out.append({"file_id": m["file_id"], "name": m["name"],
                        "형식": m["ext"], "크기": f"{m['size'] / 1024:.0f}KB"})
    return out


def count_user_files(user_id: str) -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM uploads WHERE user_id=?",
                         (user_id,)).fetchone()[0]


def purge_user(user_id: str) -> int:
    """한 사람이 올린 파일을 지운다. **디스크에서도 지운다.**

    표만 지우면 파일은 그대로 남는다. 이력서 같은 것이 폴더에 남아 있는데
    아무 화면에도 안 나오는 상태가 제일 나쁘다 — 지운 줄 알고 잊어버린다.
    """
    n = 0
    with _conn() as c:
        rows = c.execute("SELECT file_id, path FROM uploads WHERE user_id=?",
                         (user_id,)).fetchall()
        for r in rows:
            try:
                (ROOT / r["path"]).unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass          # 파일이 이미 없어도 표는 지운다
            c.execute("DELETE FROM upload_text WHERE file_id=?", (r["file_id"],))
            n += 1
        c.execute("DELETE FROM upload_sent WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM uploads WHERE user_id=?", (user_id,))
    return n


def remove(file_id: str, user_id: str) -> bool:
    """파일 하나를 지운다. **본인 것만.** 디스크에서도 지운다.

    보통은 보관 기간(UPLOAD_KEEP_DAYS)이 지나면 알아서 사라진다.
    이 함수는 **그때까지 두면 안 되는 것**을 위한 것이다.
    재무 자료를 앱에 넘기고 나면, 포털에 30일씩 남을 이유가 없다.
    """
    with _conn() as c:
        r = c.execute("SELECT path FROM uploads WHERE file_id=? AND user_id=?",
                      (file_id, user_id)).fetchone()
        if not r:
            return False
        try:
            (ROOT / r["path"]).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass          # 파일이 이미 없어도 표는 지운다
        c.execute("DELETE FROM upload_text WHERE file_id=?", (file_id,))
        c.execute("DELETE FROM upload_sent WHERE file_id=?", (file_id,))
        c.execute("DELETE FROM uploads WHERE file_id=?", (file_id,))
    return True


def purge_old() -> int:
    """보관 기간이 지난 파일을 지운다. 서버가 뜰 때 한 번 돈다.

    이력서 같은 것이 몇 년씩 남아 있을 이유가 없다.
    """
    if KEEP_DAYS <= 0:
        return 0
    with _conn() as c:
        rows = c.execute(
            "SELECT file_id, path FROM uploads WHERE created_at < datetime('now', ?)",
            (f"-{KEEP_DAYS} days",),
        ).fetchall()
        for r in rows:
            try:
                (ROOT / r["path"]).unlink(missing_ok=True)
            except OSError:
                pass          # 파일이 이미 없어도 기록은 지운다
        c.execute(
            "DELETE FROM uploads WHERE created_at < datetime('now', ?)",
            (f"-{KEEP_DAYS} days",),
        )
        # 뽑아 둔 글자도 같이 지운다. 파일은 지웠는데 내용만 남으면
        # 보관 기간을 정해 둔 의미가 없다.
        ids = [(r["file_id"],) for r in rows]
        c.executemany("DELETE FROM upload_text WHERE file_id=?", ids)
        c.executemany("DELETE FROM upload_sent WHERE file_id=?", ids)
    return len(rows)


# ── 앱으로 넘기기 ────────────────────────────────────────────
def multipart(field: str, filename: str, blob: bytes,
              extra: dict | None = None) -> tuple[bytes, str]:
    """multipart/form-data 본문을 만든다. 표준 라이브러리만 쓴다.

    requests 를 쓰면 한 줄이지만, 포털은 의존성을 최소로 유지한다.
    (requirements.txt 가 짧을수록 배포와 보안 점검이 단순해진다)
    """
    boundary = "----portal" + secrets.token_hex(16)
    b = boundary.encode()
    parts = []
    for k, v in (extra or {}).items():
        parts += [b"--" + b,
                  f'Content-Disposition: form-data; name="{k}"'.encode(),
                  b"", str(v).encode()]
    parts += [b"--" + b,
              f'Content-Disposition: form-data; name="{field}"; '
              f'filename="{filename}"'.encode("utf-8"),
              b"Content-Type: application/octet-stream",
              b"", blob,
              b"--" + b + b"--", b""]
    return b"\r\n".join(parts), f"multipart/form-data; boundary={boundary}"
