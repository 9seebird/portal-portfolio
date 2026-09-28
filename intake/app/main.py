"""앱 입고 — 만든 앱을 올리면 규칙에 맞는지 기계가 먼저 보고, 담당자 검토로 넘어간다.

왜 만들었나
──────────
다른 부서에서 만든 앱을 받으면 담당자가 점검 스크립트를 돌려 보고, ✗ 가 있으면
알려 주고, 고쳐서 다시 받고를 반복했다. 오가는 횟수만큼 시간이 든다.
**만든 사람이 스스로 돌려 볼 수 있게 하면 그 왕복이 사라진다.**
담당자에게 오는 시점에 이미 절반은 걸러져 있다.

흐름은 넷이다
────────────
    올린다 → 기계가 본다 → (통과하면) 검토 요청 → 담당자가 승인·반려

✗ 가 있으면 요청 버튼이 안 열린다. 기계가 잡을 수 있는 것을 사람에게
넘기지 않는다. 대신 **무엇을 어떻게 고치면 되는지 프롬프트로 만들어 준다**
(fixes.py). 만든 사람이 쓰던 AI 에 그대로 붙여넣으면 된다.

체험판에서는 올리기를 받지 않는다
────────────────────────────────
이 앱은 이 포털에서 유일하게 **남이 준 파일을 서버에서 푸는** 앱이다.
공개된 곳에 그 길을 열어 둘 이유가 없어서, 미리 넣어 둔 예시 셋 중에서 고르게 한다.

예시도 **zip 으로 두었다.** 폴더로 두면 두 가지가 나빠진다 —
검사기가 이 앱을 검사할 때 안에 든 「일부러 틀린 예시」까지 같이 잡고,
예시만 다른 코드 길로 들어가서 「예시에서는 되는데」가 생긴다.
지금은 예시도 올린 파일과 **글자 그대로 같은 함수**를 지난다. 푸는 단계만 없다.

사내에서는 DEMO_MODE=0 으로 두고 그대로 올려서 쓴다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               PlainTextResponse)
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from . import ai_edit, ai_fix, changes, db, demo_limit, demo_seed, fixes, portal
from .auth import current_user, require_admin, require_user
from .checker import BadZip, run
from .service_id import check_service_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("intake")

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
DEMO = str(os.getenv("DEMO_MODE", "0")).strip().lower() in ("1", "true", "yes", "on")
STATIC = Path(__file__).parent / "static"
SAMPLES = Path(os.getenv("SAMPLES_DIR", "/app/samples"))
ZIP_DIR = db.DATA_DIR / "zips"

# 예시 셋. **일부러 하나는 깨끗하고, 하나는 엉망이고, 하나는 그 사이다.**
# 전부 통과하는 예시만 두면 이 도구가 무엇을 잡아내는지 안 보인다.
SAMPLES_META = [
    {"id": "회의실예약", "sid": "meeting-room", "label": "규칙대로 만든 앱",
     "hint": "포털 헤더를 읽고, 자기 등록을 하고, 주소는 상대경로. 통과합니다."},
    {"id": "출입증관리", "sid": "badge-pass", "label": "로그인을 스스로 만든 앱",
     "hint": "잘 만든 것 같지만 로그인을 따로 만들었습니다. 포털 권한과 두 겹이 됩니다."},
    {"id": "비품신청", "sid": "supply-request", "label": "여기저기 틀린 앱",
     "hint": "바깥 포트를 열고, 떠다니는 태그를 쓰고, 주소가 절대경로입니다."},
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    ZIP_DIR.mkdir(parents=True, exist_ok=True)
    await portal.register_service()
    if DEMO:
        # 예시 이력은 화면을 막지 않고 뒤에서 깐다. 검사 스크립트를 세 번
        # 돌리는 동안(몇 초) 첫 화면이 기다리면 안 된다.
        asyncio.create_task(demo_seed.ensure(SAMPLES, SAMPLES_META, force=True))
    yield


app = FastAPI(title="앱 입고", lifespan=lifespan)


def _page(name: str) -> HTMLResponse:
    return HTMLResponse((STATIC / name).read_text(encoding="utf-8"))


# ── 기본 ───────────────────────────────────────────────────────────
@app.get("/api/health")
async def health() -> dict:
    """살아 있는지 확인하는 주소 (규칙 4)."""
    return {"ok": True, "service": portal.SERVICE_ID}


@app.get("/api/mode")
async def mode() -> dict:
    """화면이 올리기 칸을 그릴지 예시 목록을 그릴지 이 값으로 정한다."""
    return {"demo": DEMO, "samples": SAMPLES_META if DEMO else [],
            "max_upload_mb": MAX_UPLOAD_MB}


@app.get("/api/me")
async def me(request: Request) -> dict:
    return require_user(request)


# ── 배지 ───────────────────────────────────────────────────────────
# 포털 첫 화면의 앱 카드에 숫자를 띄우기 위한 통로.
# 포털은 앱마다 이 주소를 한 번씩 물어보고, count 가 0 보다 크면 배지를 붙인다.
# 규칙은 앱 전체에 공통이다 — 배지를 내고 싶은 앱은 이것과 똑같은 모양으로
# /api/badge 를 만들면 된다. 포털은 그 외의 것을 알 필요가 없다.
#
#   200 {"count": 2, "label": "검토 요청 2건"}   ← 배지 붙음
#   200 {"count": 0, "label": ""}                ← 배지 없음
#   401/403/그 밖의 실패                          ← 포털이 조용히 넘어감
#
# 볼 일이 없는 사람에게는 0 을 준다. 여기서는 담당자가 아니면 늘 0 이다.
@app.get("/api/badge")
async def badge(request: Request) -> dict:
    user = current_user(request)
    if user["role"] != "admin":
        return {"count": 0, "label": ""}
    with db.connect() as con:
        n = int(con.execute(
            "SELECT COUNT(*) FROM intakes WHERE status = 'requested'").fetchone()[0] or 0)
    return {"count": n, "label": f"검토 요청 {n}건" if n else ""}


# ── 서비스 ID 중복 확인 ────────────────────────────────────────────
# 화면이 입력 중에 물어본다. 판정은 넷 중 하나다.
#
#   free      아직 아무도 안 쓴 주소
#   portal    포털에 이미 등록된 서비스 → 고쳐 올리는 것이면 맞다
#   pending   포털엔 없지만 여기에 같은 ID 로 올린 것이 이미 있다
#   unknown   포털에 못 물어봤다 → **비었다고 말하지 않는다**
#
# **막지 않는다.** 이미 있는 앱을 고쳐 올릴 때는 같은 ID 가 정답이다.
# 기계는 "이건 이미 있습니다" 까지만 말하고, 맞는지는 사람이 판단한다.
@app.get("/api/service-id/check")
async def service_id_check(request: Request, v: str = "") -> dict:
    require_user(request)
    value, why = check_service_id(v)
    if why:
        return {"value": value, "kind": "bad", "reason": why}

    ids = await portal.taken_ids()
    if ids is not None and value in ids:
        return {"value": value, "kind": "portal", "name": ids[value],
                "reason": f"포털에 이미 있는 주소입니다 — 「{ids[value] or value}」."}

    with db.connect() as con:
        row = con.execute(
            "SELECT title, actor_name, ts FROM intakes "
            " WHERE service_id = ? ORDER BY id DESC LIMIT 1", (value,)).fetchone()
    if row:
        row = dict(row)
        who = row["actor_name"] or "누군가"
        when = (row["ts"] or "")[:10]
        return {"value": value, "kind": "pending", "name": row["title"] or "",
                "reason": f"{who} 님이 {when} 에 같은 주소로 올린 것이 있습니다."}

    if ids is None:
        # 포털에 한 번도 못 물어봤다. 여기 이력에도 없다. 그래도 포털에
        # 있을 수 있으므로 "비었다" 고 말하지 않는다.
        return {"value": value, "kind": "unknown", "name": "",
                "reason": "포털에 물어보지 못했습니다. 이미 쓰는 주소인지 확인되지 않았습니다."}

    return {"value": value, "kind": "free", "name": "",
            "reason": "아직 아무도 안 쓰는 주소입니다."}


# ── 제출 ───────────────────────────────────────────────────────────
def _store(result: dict, *, service_id: str, title: str, note: str, user: dict,
           zip_name: str, zip_bytes: int, sample_id: str | None,
           sha256: str = "") -> int:
    """검사 결과를 제출물로 남긴다. 아직 담당자에게 가지 않은 상태(checked)다."""
    t = result["tally"]
    with db.connect() as con:
        cur = con.execute(
            """INSERT INTO intakes
               (ts, service_id, title, note, actor_id, actor_name, actor_dept,
                zip_name, sample_id, zip_bytes, zip_sha256,
                ok_count, warn_count, bad_count, verdict, report, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'checked')""",
            (db.now_kst(), service_id, title or service_id, note,
             user.get("id"), user.get("name"), user.get("dept"),
             zip_name, sample_id, zip_bytes, sha256,
             t["ok"], t["warn"], t["bad"], result["verdict"], result.get("raw", "")),
        )
        intake_id = int(cur.lastrowid)
        db.add_event(
            con, kind="intake", service_id=service_id, actor=user,
            summary=f"{title or service_id} 제출 · 검수 {result['verdict']}",
            status=result["verdict"], ref_id=intake_id,
            meta={"zip": zip_name, "bytes": zip_bytes,
                  "ok": t["ok"], "warn": t["warn"], "bad": t["bad"]},
        )
        con.commit()
    return intake_id


@app.post("/api/intakes")
async def create_intake(
    request: Request,
    file: UploadFile | None = File(default=None),
    sample_id: str = Form(default=""),
    service_id: str = Form(default=""),
    title: str = Form(default=""),
    note: str = Form(default=""),
) -> JSONResponse:
    """앱 하나를 제출한다.

    체험판은 `sample_id` 로 예시를 고른다. 사내판은 `file` 로 zip 을 올린다.
    **검사하는 함수는 같다** — 예시만 다른 길로 들어가면 「예시에서는 되는데」가 된다.
    """
    user = require_user(request)

    if sample_id:
        meta = next((s for s in SAMPLES_META if s["id"] == sample_id), None)
        if not meta:
            raise HTTPException(404, "그런 예시가 없습니다.")
        # ★ 목록에 있는 이름만 받는다. 경로를 그대로 이어 붙이면
        #   ../../ 같은 것으로 폴더 밖을 검사시킬 수 있다.
        path = SAMPLES / f'{meta["id"]}.zip'
        if not path.is_file():
            raise HTTPException(500, "예시 파일이 없습니다.")
        data = path.read_bytes()
        result = await run(data, path.name)
        intake_id = _store(result, service_id=meta["sid"], title=meta["id"],
                           note=meta["hint"], user=user, zip_name=path.name,
                           zip_bytes=len(data), sample_id=meta["id"],
                           sha256=hashlib.sha256(data).hexdigest())
        # AI 로 고칠 때 원본이 필요하다. 예시도 올린 것과 같은 자리에 둔다.
        (ZIP_DIR / f"{intake_id}.zip").write_bytes(data)
        await portal.send_audit("앱 제출(예시)", user, f'{meta["sid"]} · {meta["label"]}')
        return JSONResponse({"id": intake_id, "name": meta["label"], "sample": meta, **result})

    if DEMO:
        raise HTTPException(
            403, "체험판에서는 파일을 올릴 수 없습니다. 아래 예시 중에서 골라 보세요.")

    if file is None:
        raise HTTPException(400, "zip 파일을 골라 주세요.")

    service_id, why = check_service_id(service_id)
    if why:
        raise HTTPException(400, why)

    data = await file.read()
    size_mb = len(data) / 1024 / 1024
    if size_mb > MAX_UPLOAD_MB:
        raise HTTPException(413, f"파일이 너무 큽니다 ({size_mb:.0f}MB). "
                                 f"{MAX_UPLOAD_MB}MB까지만 받습니다.")
    if not data:
        raise HTTPException(400, "빈 파일입니다.")

    try:
        result = await run(data, file.filename or "app.zip")
    except BadZip as exc:
        # 사람에게 그대로 보여 줄 수 있는 말이다. 500 으로 감추지 않는다.
        raise HTTPException(400, str(exc)) from None
    except Exception as exc:  # noqa: BLE001
        log.exception("점검 중 오류")
        raise HTTPException(500, f"점검 중 오류가 났습니다: {type(exc).__name__}") from None

    intake_id = _store(result, service_id=service_id, title=title.strip(),
                       note=note.strip(), user=user,
                       zip_name=file.filename or "app.zip", zip_bytes=len(data),
                       sample_id=None, sha256=hashlib.sha256(data).hexdigest())
    # 담당자가 원본을 받아 깃에 올려야 하므로 올린 파일은 남긴다.
    (ZIP_DIR / f"{intake_id}.zip").write_bytes(data)
    t = result["tally"]
    await portal.send_audit("앱 제출", user,
                            f"{service_id} — ✓{t['ok']} △{t['warn']} ✗{t['bad']}")
    return JSONResponse({"id": intake_id, **result})


# ── 조회 ───────────────────────────────────────────────────────────
def _visible(row: dict, user: dict) -> bool:
    return user["role"] == "admin" or row["actor_id"] == user["id"]


@app.get("/api/intakes")
async def list_intakes(request: Request, status: str = "", mine: int = 0) -> dict:
    user = require_user(request)
    # 한동안 아무도 안 쓴 뒤에 들어온 사람은 깨끗한 줄을 봐야 한다.
    # 앞사람이 전부 반려해 두었으면 볼 것이 없기 때문이다.
    if DEMO:
        await demo_seed.ensure(SAMPLES, SAMPLES_META)
    where, args = [], []
    if user["role"] != "admin" or mine:
        where.append("actor_id = ?")
        args.append(user["id"])
    if status:
        where.append("status = ?")
        args.append(status)
    sql = ("SELECT id, ts, service_id, title, actor_id, actor_name, actor_dept, "
           "zip_name, sample_id, zip_bytes, ok_count, warn_count, bad_count, verdict, "
           "status, admin_name, admin_note, decided_at, kind, base_bad FROM intakes")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT 300"
    with db.connect() as con:
        rows = [dict(r) for r in con.execute(sql, args).fetchall()]
    return {"items": rows, "me": user}


@app.get("/api/intakes/{intake_id}")
async def get_intake(request: Request, intake_id: int) -> dict:
    user = require_user(request)
    with db.connect() as con:
        row = con.execute("SELECT * FROM intakes WHERE id = ?", (intake_id,)).fetchone()
    if not row:
        raise HTTPException(404, "없는 제출물입니다.")
    row = dict(row)
    if not _visible(row, user):
        raise HTTPException(403, "내가 올린 것만 볼 수 있습니다.")

    # 담당자가 승인 뒤에 할 일이 갈린다. 포털에 이미 있는 서비스면 깃에
    # 올려 다시 배포하면 끝이고, 없는 서비스면 포털 등록·접근 권한·nginx
    # 설정이 더 붙는다. 포털을 못 물어봤으면 None — 화면이 그 줄을 안 그린다.
    ids = await portal.taken_ids()
    row["portal_known"] = None if ids is None else (row["service_id"] in ids)
    row["portal_name"] = (ids or {}).get(row["service_id"], "")
    return row


@app.get("/api/intakes/{intake_id}/fix-prompt")
async def fix_prompt(request: Request, intake_id: int) -> JSONResponse:
    """걸린 항목을 「그대로 붙여넣어 고칠 수 있는 글」로 만들어 준다.

    반려 사유를 사람 말로 적어 주는 것만으로는 부족하다. 만든 사람은
    대개 비개발자고, 쓰던 AI 에 무엇을 말해야 할지를 모른다.
    """
    user = require_user(request)
    with db.connect() as con:
        row = con.execute("SELECT * FROM intakes WHERE id = ?", (intake_id,)).fetchone()
    if not row:
        raise HTTPException(404, "없는 제출물입니다.")
    row = dict(row)
    if not _visible(row, user):
        raise HTTPException(403, "내가 올린 것만 볼 수 있습니다.")
    text = fixes.build(report=row.get("report") or "",
                       service_id=row["service_id"],
                       title=row.get("title") or row["service_id"],
                       verdict=row.get("verdict") or "")
    return JSONResponse({"text": text})


@app.get("/api/intakes/{intake_id}/zip")
async def download_zip(request: Request, intake_id: int) -> FileResponse:
    """담당자가 원본을 받아 간다. 체험판에서는 예시 zip 그대로다."""
    user = require_user(request)
    with db.connect() as con:
        row = con.execute("SELECT * FROM intakes WHERE id = ?", (intake_id,)).fetchone()
    if not row:
        raise HTTPException(404, "없는 제출물입니다.")
    row = dict(row)
    if not _visible(row, user):
        raise HTTPException(403, "내가 올린 것만 받을 수 있습니다.")

    if row.get("sample_id"):
        meta = next((s for s in SAMPLES_META if s["id"] == row["sample_id"]), None)
        if not meta:
            raise HTTPException(404, "예시 파일이 없습니다.")
        path = SAMPLES / f'{meta["id"]}.zip'
    else:
        path = ZIP_DIR / f"{intake_id}.zip"
    if not path.is_file():
        raise HTTPException(404, "원본 파일이 없습니다.")
    return FileResponse(path, media_type="application/zip",
                        filename=row["zip_name"] or f'{row["service_id"]}.zip')


# ── 검토 요청 · 결정 ───────────────────────────────────────────────
@app.post("/api/intakes/{intake_id}/request")
async def request_review(request: Request, intake_id: int) -> dict:
    user = require_user(request)
    with db.connect() as con:
        row = con.execute("SELECT * FROM intakes WHERE id = ?", (intake_id,)).fetchone()
        if not row:
            raise HTTPException(404, "없는 제출물입니다.")
        row = dict(row)
        if row["actor_id"] != user["id"] and user["role"] != "admin":
            raise HTTPException(403, "내가 올린 것만 요청할 수 있습니다.")
        if row.get("kind") == "edit" and row["verdict"] == "bad":
            # 이미 돌고 있는 서비스는 원래 ✗ 가 있을 수 있다. 고치면서 **늘리지만** 않으면 된다.
            if row["bad_count"] > (row["base_bad"] or 0):
                raise HTTPException(400, "고치면서 ✗ 가 늘었습니다. 이대로는 요청할 수 없습니다.")
        elif row["verdict"] in ("bad", "error"):
            raise HTTPException(400, "✗ 가 있는 상태로는 요청할 수 없습니다. 고쳐서 다시 올려 주세요.")
        if row["status"] != "checked":
            raise HTTPException(400, "이미 요청했거나 처리된 제출물입니다.")

        # 같은 사람이 같은 서비스를 고쳐서 다시 올린 것이면, 앞서 요청해 둔
        # 것은 여기서 내린다. 안 그러면 담당자 목록에 같은 앱이 두 줄로 뜨고
        # 어느 zip 을 받아야 하는지 알 수 없다 — 낡은 zip 을 깃에 올리는
        # 사고가 여기서 난다. 줄을 지우지는 않는다. 상태만 바꿔 이력에 남긴다.
        old = con.execute(
            "SELECT id FROM intakes "
            " WHERE service_id = ? AND actor_id = ? AND status = 'requested' AND id <> ?",
            (row["service_id"], row["actor_id"], intake_id)).fetchall()
        if old:
            con.execute(
                "UPDATE intakes SET status = 'superseded', admin_note = ?, decided_at = ? "
                " WHERE service_id = ? AND actor_id = ? AND status = 'requested' AND id <> ?",
                (f"#{intake_id} 로 다시 올려서 내렸습니다.", db.now_kst(),
                 row["service_id"], row["actor_id"], intake_id))

        con.execute("UPDATE intakes SET status = 'requested' WHERE id = ?", (intake_id,))
        db.add_event(con, kind="intake", service_id=row["service_id"], actor=user,
                     summary=f"{row['title']} 검토 요청"
                             + (f" (앞서 요청한 {len(old)}건은 내림)" if old else ""),
                     status="requested", ref_id=intake_id)
        con.commit()
    await portal.send_audit("검토 요청", user, f"{row['service_id']} · {row['title']}")
    return {"ok": True, "status": "requested"}


@app.post("/api/intakes/{intake_id}/decide")
async def decide(request: Request, intake_id: int) -> dict:
    admin = require_admin(request)
    body = await request.json()
    decision = (body.get("decision") or "").strip()
    note = (body.get("note") or "").strip()
    if decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision 은 approved 또는 rejected 입니다.")
    with db.connect() as con:
        row = con.execute("SELECT * FROM intakes WHERE id = ?", (intake_id,)).fetchone()
        if not row:
            raise HTTPException(404, "없는 제출물입니다.")
        row = dict(row)
        if row["status"] not in ("requested", "checked"):
            raise HTTPException(400, "이미 처리된 제출물입니다.")
        con.execute(
            "UPDATE intakes SET status = ?, admin_id = ?, admin_name = ?, "
            "       admin_note = ?, decided_at = ? WHERE id = ?",
            (decision, admin.get("id"), admin.get("name"), note, db.now_kst(), intake_id))
        db.add_event(con, kind="intake", service_id=row["service_id"], actor=admin,
                     summary=f"{row['title']} {'승인' if decision == 'approved' else '반려'}"
                             + (f" — {note}" if note else ""),
                     status=decision, ref_id=intake_id)
        con.commit()
    await portal.send_audit("승인" if decision == "approved" else "반려", admin,
                            f"{row['service_id']} · {row['title']}"
                            + (f" — {note}" if note else ""))
    return {"ok": True, "status": decision}


# ── 장부 ───────────────────────────────────────────────────────────
@app.get("/api/ledger")
async def get_ledger(request: Request, days: int = 30) -> dict:
    """서비스별로 무슨 일이 몇 번 있었고 비용이 얼마인지.

    입고·AI 작업·배포가 같은 표에 같은 모양으로 쌓여서 한 줄로 뽑힌다.
    지금은 입고만 들어 있고, 코딩 에이전트를 붙이면 그 비용이 같은 자리로 온다.
    """
    require_admin(request)
    if DEMO:
        await demo_seed.ensure(SAMPLES, SAMPLES_META)
    with db.connect() as con:
        rows = db.ledger(con, days=days)
        recent = [dict(r) for r in con.execute(
            "SELECT id, ts, kind, service_id, actor_name, summary, status, "
            "       tokens_in, tokens_out, cost_krw FROM events "
            " ORDER BY id DESC LIMIT 100").fetchall()]
    return {"days": days, "by_service": rows, "recent": recent}


# ── AI 로 고치기 ───────────────────────────────────────────────────
# 사내판(app-intake)과 **같은 모듈**을 그대로 쓴다 (ai_fix · ai_edit · changes).
# 체험판에서 다른 것은 세 가지뿐이다.
#   · AI 를 진짜로 부르지만 하루 횟수를 막는다 (demo_limit).
#   · 「미리 띄워 보기」는 설명만 보여 준다 — 공개된 서버에서 남의 컨테이너를
#     띄우는 길을 열어 둘 이유가 없다. 사내판에는 실제로 띄우는 실행기가 있다.
#   · 담당자 지정이 없다. 사내판은 「그 앱의 담당자 + 포털 관리자」에게만 보인다.
def _load_intake(intake_id: int) -> dict:
    with db.connect() as con:
        row = con.execute("SELECT * FROM intakes WHERE id = ?", (intake_id,)).fetchone()
    if not row:
        raise HTTPException(404, "없는 제출물입니다.")
    return dict(row)


@app.get("/api/ai")
async def ai_status(request: Request) -> dict:
    """AI 를 쓸 수 있는지, 오늘 몇 번 남았는지. 화면이 버튼을 잠글 때 쓴다."""
    require_user(request)
    out = {"enabled": ai_fix.enabled(), "demo": DEMO, "model": ai_fix.MODEL}
    if DEMO:
        out["limit"] = await run_in_threadpool(demo_limit.status)
    return out


def _guard(*, gap: bool = True) -> None:
    """체험판이면 하루 상한을 본다. 사내판에서는 아무것도 하지 않는다."""
    if not ai_fix.enabled():
        raise HTTPException(400, "AI 수정이 꺼져 있습니다. (AI_API_KEY 가 없습니다)")
    if DEMO:
        try:
            demo_limit.check(gap=gap)
        except demo_limit.Blocked as e:
            raise HTTPException(429, str(e)) from None


@app.post("/api/intakes/{intake_id}/ai-fix")
async def run_ai_fix(request: Request, intake_id: int) -> JSONResponse:
    """✗ 가 있는 제출물을 AI 가 고쳐서 **새 제출물**로 남긴다. 원본은 그대로 둔다."""
    user = require_user(request)
    _guard()
    row = _load_intake(intake_id)
    if not _visible(row, user):
        raise HTTPException(403, "내가 올린 것만 고칠 수 있습니다.")
    if row["verdict"] != "bad":
        raise HTTPException(400, "✗ 가 있는 제출물만 AI 로 고칠 수 있습니다.")
    src = ZIP_DIR / f"{intake_id}.zip"
    if not src.exists():
        raise HTTPException(404, "원본 파일이 없습니다.")

    try:
        fx = await run_in_threadpool(
            ai_fix.run, src, report=row["report"] or "", service_id=row["service_id"],
            title=row["title"] or "", verdict=row["verdict"])
    except ai_fix.AIFixError as e:
        with db.connect() as con:
            db.add_event(con, kind="agent_run", service_id=row["service_id"], actor=user,
                         summary=f"#{intake_id} AI 수정 실패 — {e}"[:500], status="error",
                         ref_id=intake_id, meta={"from": intake_id, "model": ai_fix.MODEL})
            con.commit()
        raise HTTPException(502, str(e)) from None

    result, tmp = fx["result"], fx["zip"]
    try:
        data = tmp.read_bytes()
        stem = (row["zip_name"] or row["service_id"]).removesuffix(".zip")
        with db.connect() as con:
            cur = con.execute(
                """INSERT INTO intakes
                   (ts, service_id, title, note, actor_id, actor_name, actor_dept,
                    zip_name, zip_bytes, zip_sha256,
                    ok_count, warn_count, bad_count, verdict, report, status, kind)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'checked','new')""",
                (db.now_kst(), row["service_id"], row["title"],
                 f"[AI 수정] #{intake_id} 원본을 AI 가 고쳤습니다.\n\n{fx['summary']}".strip(),
                 row["actor_id"], row["actor_name"], row["actor_dept"],
                 f"{stem}_AI수정.zip", len(data), hashlib.sha256(data).hexdigest(),
                 result.get("ok", 0), result.get("warn", 0), result.get("bad", 0),
                 result["verdict"], result["report"]))
            new_id = int(cur.lastrowid)
            db.add_event(
                con, kind="agent_run", service_id=row["service_id"], actor=user,
                summary=f"#{intake_id} AI 수정 → #{new_id} · 검수 {result['verdict']}",
                status=result["verdict"], ref_id=new_id,
                tokens_in=fx["tokens_in"], tokens_out=fx["tokens_out"],
                cost_krw=fx["cost_krw"], duration_ms=fx["duration_ms"],
                meta={"from": intake_id, "model": fx["model"], "rounds": fx["rounds"],
                      "files": fx["files"], "refused": fx["refused"]})
            con.commit()
        shutil.move(str(tmp), str(ZIP_DIR / f"{new_id}.zip"))
        (ZIP_DIR / f"{new_id}.diff.txt").write_text(fx["diff"], encoding="utf-8")
    finally:
        tmp.unlink(missing_ok=True)

    await portal.send_audit("AI 수정", user, f"{row['service_id']} · #{intake_id} → #{new_id}")
    return JSONResponse({"id": new_id, "from": intake_id, "summary": fx["summary"],
                         "diff": fx["diff"], "files": fx["files"], "refused": fx["refused"],
                         **{k: result.get(k) for k in ("verdict", "ok", "warn", "bad", "report")},
                         **{k: fx[k] for k in ("tokens_in", "tokens_out", "cost_krw",
                                               "duration_ms", "rounds")}})


# ── 기존 서비스 고치기 ─────────────────────────────────────────────
async def _editable_services(user: dict) -> tuple[list[dict], bool]:
    """(고칠 수 있는 서비스, 포털에 물어봤는가).

    목록은 포털 첫 화면의 카드 이름·순서를 그대로 따른다 (ai_edit.catalog).
    사내판은 여기서 「그 앱의 담당자인가」를 한 번 더 걸러 낸다. 체험판에는
    담당자 지정이 없어서 들어온 사람 모두에게 보인다 — 보여 주려고 만든 화면이다.
    """
    names = await portal.taken_ids()
    if names is None:
        return [], False
    return ai_edit.catalog(names), True


@app.get("/api/services")
async def list_services(request: Request) -> dict:
    user = require_user(request)
    items, portal_ok = await _editable_services(user)
    out = {"items": items, "enabled": ai_fix.enabled(), "portal_ok": portal_ok,
           "repo_ok": ai_edit.REPO.is_dir() and any(ai_edit.REPO.iterdir())}
    if DEMO:
        out["limit"] = await run_in_threadpool(demo_limit.status)
    return out


async def _entry(user: dict, service_id: str) -> dict:
    items, _ = await _editable_services(user)
    entry = next((x for x in items if x["id"] == service_id), None)
    if entry is None:
        raise HTTPException(403, "고칠 수 없는 서비스입니다.")
    return entry


@app.get("/api/services/{service_id}/source")
async def download_source(request: Request, service_id: str) -> FileResponse:
    """지금 돌고 있는 그 서비스의 코드를 zip 으로 받는다.

    자기가 쓰던 AI 도구로 고치고 싶은 사람을 위한 길이다. 비밀값(.env)과
    운영 자료(data/)는 넣지 않는다.
    """
    user = require_user(request)
    entry = await _entry(user, service_id)
    try:
        path = await run_in_threadpool(ai_edit.source_zip, entry["folder"])
    except ai_fix.AIFixError as e:
        raise HTTPException(400, str(e)) from None
    await portal.send_audit("서비스 코드 내려받기", user, f"{service_id} ({entry['folder']})")
    return FileResponse(path, media_type="application/zip",
                        filename=f"{entry['folder']}_현재코드.zip",
                        background=BackgroundTask(lambda: path.unlink(missing_ok=True)))


@app.post("/api/services/{service_id}/ai-edit")
async def run_ai_edit(request: Request, service_id: str) -> JSONResponse:
    """요청 한 줄로 이미 돌고 있는 서비스를 고쳐 본다. 저장소에는 쓰지 않는다."""
    user = require_user(request)
    _guard()
    entry = await _entry(user, service_id)
    body = await request.json()
    ask = (body.get("request") or "").strip()[:4000]
    if len(ask) < 5:
        raise HTTPException(400, "무엇을 고칠지 한 줄로 적어 주세요.")
    try:
        fx = await run_in_threadpool(ai_edit.run, entry, ask)
    except ai_fix.AIFixError as e:
        tin, tout = getattr(e, "tokens", (0, 0))
        with db.connect() as con:
            db.add_event(con, kind="agent_run", service_id=service_id, actor=user,
                         summary=f"기존 서비스 AI 수정 실패 — {e}"[:500], status="error",
                         tokens_in=tin, tokens_out=tout,
                         cost_krw=round(tin / 1e6 * ai_fix.PRICE_IN_KRW
                                        + tout / 1e6 * ai_fix.PRICE_OUT_KRW, 1),
                         meta={"request": ask[:500], "model": ai_fix.MODEL})
            con.commit()
        raise HTTPException(502, str(e)) from None

    result, base, tmp = fx["result"], fx["base"], fx["zip"]
    note = f"[기존 서비스 고치기] 요청: {ask}\n\n{fx['summary']}"
    if fx["human"]:
        note += f"\n\n[사람이 할 일]\n{fx['human']}"
    try:
        data = tmp.read_bytes()
        with db.connect() as con:
            cur = con.execute(
                """INSERT INTO intakes
                   (ts, service_id, title, note, actor_id, actor_name, actor_dept,
                    zip_name, zip_bytes, zip_sha256,
                    ok_count, warn_count, bad_count, verdict, report, status, kind, base_bad)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'checked','edit',?)""",
                (db.now_kst(), service_id, entry["title"], note.strip(),
                 user["id"], user["name"], user["dept"],
                 f"{service_id}_AI수정.zip", len(data), hashlib.sha256(data).hexdigest(),
                 result.get("ok", 0), result.get("warn", 0), result.get("bad", 0),
                 result["verdict"], result["report"], base.get("bad", 0)))
            new_id = int(cur.lastrowid)
            db.add_event(
                con, kind="agent_run", service_id=service_id, actor=user,
                summary=f"기존 서비스 AI 수정 → #{new_id} · {ask[:80]}",
                status=result["verdict"], ref_id=new_id,
                tokens_in=fx["tokens_in"], tokens_out=fx["tokens_out"],
                cost_krw=fx["cost_krw"], duration_ms=fx["duration_ms"],
                meta={"request": ask[:500], "model": fx["model"], "rounds": fx["rounds"],
                      "files": fx["files"], "failed": len(fx["failed"])})
            con.commit()
        shutil.move(str(tmp), str(ZIP_DIR / f"{new_id}.zip"))
        (ZIP_DIR / f"{new_id}.diff.txt").write_text(fx["diff"], encoding="utf-8")
        (ZIP_DIR / f"{new_id}.folder.txt").write_text(entry["folder"], encoding="utf-8")
    finally:
        tmp.unlink(missing_ok=True)

    await portal.send_audit("기존 서비스 AI 수정", user, f"{service_id} · #{new_id} · {ask[:80]}")
    return JSONResponse({
        "id": new_id, "kind": "edit", "service_id": service_id, "title": entry["title"],
        "folder": entry["folder"],
        **{k: result.get(k) for k in ("verdict", "ok", "warn", "bad", "report")},
        "base_bad": base.get("bad", 0), "base_warn": base.get("warn", 0),
        **{k: fx[k] for k in ("summary", "human", "diff", "files", "failed", "tokens_in",
                              "tokens_out", "cost_krw", "duration_ms", "rounds")}})


# ── 무엇이 바뀌었나 ────────────────────────────────────────────────
# 세 겹으로 보여 준다. 기계가 센 것 → 눈여겨볼 것 → AI 가 쓴 사람 말.
# 담당자가 patch 를 열어 읽지 않아도 무엇이 올라가는지 알 수 있어야 한다.
def _changes_paths(intake_id: int) -> tuple[Path, Path]:
    return ZIP_DIR / f"{intake_id}.diff.txt", ZIP_DIR / f"{intake_id}.summary.json"


def _folder_of(row: dict) -> str:
    path = ZIP_DIR / f'{row["id"]}.folder.txt'
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return row["service_id"]


def _prepare_changes(row: dict) -> dict:
    """반영 파일(.patch)이 없으면 만들고, 기계가 읽어 낸 것을 돌려준다."""
    intake_id = int(row["id"])
    patch_path, sum_path = _changes_paths(intake_id)
    folder = _folder_of(row)
    if not patch_path.exists():
        folder_path = ai_edit.REPO / folder
        if folder not in ai_edit._folders() or not folder_path.is_dir():
            return {"available": False,
                    "why": "저장소에 같은 이름의 서비스가 없어서 견줄 코드가 없습니다 "
                           "(새로 붙이는 앱입니다)."}
        got = changes.build(ZIP_DIR / f"{intake_id}.zip", folder, folder_path)
        if not got["patch"] and not got["removed"]:
            return {"available": False, "why": "지금 운영 중인 코드와 다른 곳이 없습니다."}
        patch_path.write_text(got["patch"], encoding="utf-8")
        (ZIP_DIR / f"{intake_id}.removed.txt").write_text("\n".join(got["removed"]),
                                                          encoding="utf-8")
    rm_path = ZIP_DIR / f"{intake_id}.removed.txt"
    removed = ([x for x in rm_path.read_text(encoding="utf-8").splitlines() if x]
               if rm_path.exists() else [])
    patch = patch_path.read_text(encoding="utf-8")
    out = {"available": True, "folder": folder, "removed": removed,
           **changes.analyze(patch, removed)}
    if sum_path.exists():
        out["summary"] = json.loads(sum_path.read_text(encoding="utf-8"))
    return out


@app.get("/api/intakes/{intake_id}/changes")
async def get_changes(request: Request, intake_id: int) -> dict:
    user = require_user(request)
    row = _load_intake(intake_id)
    if not _visible(row, user):
        raise HTTPException(403, "내가 올린 것만 볼 수 있습니다.")
    try:
        return await run_in_threadpool(_prepare_changes, row)
    except (OSError, zipfile.BadZipFile) as e:
        return {"available": False, "why": f"견주지 못했습니다 — {e}"}


@app.post("/api/intakes/{intake_id}/changes/summary")
async def make_summary(request: Request, intake_id: int) -> dict:
    """AI 로 사람 말 요약을 만든다. 한 제출물에 한 번만 만들고 파일로 남긴다."""
    user = require_user(request)
    row = _load_intake(intake_id)
    if not _visible(row, user):
        raise HTTPException(403, "내가 올린 것만 볼 수 있습니다.")
    info = await run_in_threadpool(_prepare_changes, row)
    if not info.get("available"):
        raise HTTPException(400, info.get("why") or "견줄 것이 없습니다.")
    patch_path, sum_path = _changes_paths(intake_id)
    if sum_path.exists():        # 이미 있으면 AI 를 또 부르지 않는다
        return json.loads(sum_path.read_text(encoding="utf-8"))
    _guard(gap=False)
    try:
        got = await run_in_threadpool(changes.ai_summary,
                                      patch_path.read_text(encoding="utf-8"),
                                      row["title"] or row["service_id"], info.get("removed"))
    except ai_fix.AIFixError as e:
        raise HTTPException(502, str(e)) from None
    sum_path.write_text(json.dumps(got, ensure_ascii=False), encoding="utf-8")
    with db.connect() as con:
        db.add_event(con, kind="agent_run", service_id=row["service_id"], actor=user,
                     summary=f"#{intake_id} 변경 요약 만듦", status="done",
                     tokens_in=got["tokens_in"], tokens_out=got["tokens_out"],
                     cost_krw=got["cost_krw"], ref_id=intake_id)
        con.commit()
    return got


@app.get("/api/intakes/{intake_id}/diff")
async def get_diff(request: Request, intake_id: int, download: int = 0) -> PlainTextResponse:
    """무엇이 바뀌었는지 (patch). 저장소 뿌리에서 `git apply` 로 그대로 들어간다."""
    user = require_user(request)
    row = _load_intake(intake_id)
    if not _visible(row, user):
        raise HTTPException(403, "내가 올린 것만 볼 수 있습니다.")
    path = _changes_paths(intake_id)[0]
    if not path.exists():
        info = await run_in_threadpool(_prepare_changes, row)
        if not info.get("available") or not path.exists():
            raise HTTPException(404, info.get("why") or "바뀐 부분을 만들 수 없습니다.")
    headers = ({"Content-Disposition":
                f'attachment; filename="{row["service_id"]}-{intake_id}.patch"'}
               if download else None)
    return PlainTextResponse(path.read_text(encoding="utf-8"), headers=headers)


# ── 미리 띄워 보기 (체험판은 설명만) ───────────────────────────────
# 사내판에는 고친 것을 **따로 띄워서 눌러 보는** 실행기가 있다. 여기서는 설명만
# 한다. 공개된 서버에서 아무나 컨테이너를 띄우는 길을 열어 둘 이유가 없다.
PREVIEW_INFO = {
    "available": False,
    "title": "미리 띄워 보기 (사내판 기능)",
    "why": "체험판에서는 설명만 보여 드립니다. 공개된 서버에서 컨테이너를 띄우는 "
           "길을 열어 두지 않습니다.",
    "how": [
        "고친 코드를 **운영과 따로** 띄운다. 운영 서비스는 그대로 돈다.",
        "임시 주소(/preview/12/)로 담당자만 들어가 실제로 눌러 본다.",
        "바깥 인터넷을 막고, 비밀값(.env)을 넣지 않고, 권한을 뺀 컨테이너로 띄운다.",
        "2시간 뒤 스스로 사라진다. 승인 전에 눌러 보고 판단할 수 있다.",
    ],
    "why_needed": "검사와 AI 요약이 통과라고 해도, 눌러 봐야 아는 것이 있다 — "
                  "실제로 이 기능으로 「드래그하면 파란 테두리가 안 지워지는」 버그를 "
                  "승인 전에 잡았다.",
}


@app.get("/api/preview-info")
async def preview_info(request: Request) -> dict:
    require_user(request)
    return PREVIEW_INFO


# ── 화면 ───────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return _page("index.html")


@app.get("/admin", response_class=HTMLResponse)
async def admin_page() -> HTMLResponse:
    return _page("admin.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
