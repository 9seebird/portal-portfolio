"""매뉴얼 가져오기 — PPT 한 개를 매뉴얼 하나로 바꾼다.

로그인은 사내 포털이 앞단에서 처리한다. 이 앱은 포털이 붙여 준 헤더만 읽는다.
매뉴얼을 통째로 갈아 끼우는 앱이므로 **담당자(admin)만** 쓸 수 있다.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from urllib.parse import unquote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from . import manuals_io as mio
from . import portal
from .pptx_parse import parse, slugify

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("manual-import")

STATIC = Path(__file__).parent / "static"
MAX_MB = int(os.getenv("MAX_UPLOAD_MB", "60"))     # 캡처가 많은 PPT 는 쉽게 커진다

app = FastAPI(title="매뉴얼 가져오기", docs_url=None, redoc_url=None)


@app.on_event("startup")
async def _startup() -> None:
    await portal.register_service()


# ── 사용자 ───────────────────────────────────────────────────
DEV_USER = {"id": "hong", "name": "홍길동", "dept": "인사총무팀", "role": "admin"}


def _dev() -> bool:
    return str(os.getenv("DEV_MODE", "false")).strip().lower() in ("1", "true", "yes", "on")


def current_user(request: Request) -> dict:
    uid = request.headers.get("X-User-Id")
    if not uid:
        if _dev():
            return dict(DEV_USER)
        raise HTTPException(status_code=401, detail="포털을 통해 접속해 주세요.")
    role = (request.headers.get("X-User-Role") or "user").strip().lower()
    return {"id": uid,
            "name": unquote(request.headers.get("X-User-Name") or ""),
            "dept": unquote(request.headers.get("X-User-Dept") or ""),
            "role": "admin" if role == "admin" else "user"}


def require_admin(request: Request) -> dict:
    """매뉴얼을 통째로 바꾸는 일이라 담당자만 할 수 있다.

    접근 범위에 든 사람이라고 아무나 덮어쓰게 두면, 되돌릴 수 없는 동작을
    누가 했는지 알 수 없게 된다.
    """
    u = current_user(request)
    if u["role"] != "admin":
        raise HTTPException(status_code=403,
                            detail="담당자만 매뉴얼을 바꿀 수 있습니다. "
                                   "포털 관리자에게 담당자 지정을 요청하세요.")
    return u


# ── 화면 ─────────────────────────────────────────────────────
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return {"user": user}


@app.get("/api/manuals")
def manuals(_: dict = Depends(current_user)):
    """지금 있는 매뉴얼 목록. 어느 것을 덮어쓰는지 화면에서 보여준다."""
    return {"manuals": mio.list_manuals()}


# ── 읽기만 ───────────────────────────────────────────────────
async def _read(file: UploadFile) -> bytes:
    name = (file.filename or "").lower()
    if not name.endswith((".pptx", ".pptm")):
        raise HTTPException(status_code=400,
                            detail="PowerPoint 파일(.pptx)만 올릴 수 있습니다. "
                                   "옛 형식(.ppt)은 PowerPoint 에서 다른 이름으로 "
                                   "저장해 .pptx 로 바꿔 주세요.")
    blob = await file.read()
    if not blob:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    if len(blob) > MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=413,
                            detail=f"파일이 너무 큽니다. {MAX_MB}MB 까지 올릴 수 있습니다.")
    if not blob.startswith(b"PK"):
        raise HTTPException(status_code=400,
                            detail="PowerPoint 파일이 아닙니다. 확장자만 바꾼 파일은 읽을 수 없습니다.")
    return blob


def _guess_id(filename: str, title: str, existing: list[dict]) -> tuple[str, str]:
    """이미 있는 매뉴얼을 가리키는 것 같으면 그 id 를 먼저 제안한다.

    "1. SAP_GUI_매뉴얼.pptx" 는 sap-gui 를 새로 만드는 게 아니라
    **고치러** 오는 파일이다. 새 id 를 지어 주면 같은 매뉴얼이 둘이 된다.
    """
    # ① 전에 이 파일 이름으로 올린 적이 있으면 두말할 것 없이 그 매뉴얼이다.
    #    "같은 파일이면 고치는 것, 새 파일이면 새로 만드는 것" 이 사람이
    #    머릿속에 그리는 규칙이고, 파일 이름이 그 규칙의 열쇠다.
    fname = (filename or "").strip().lower()
    for m in existing:
        if fname and (m.get("source") or "").strip().lower() == fname:
            return m["id"], "전에 같은 이름의 파일로 올린 매뉴얼입니다"

    slug = slugify(filename)
    ids = [m["id"] for m in existing if m.get("id")]
    if not slug:
        return "", ""
    if slug in ids:
        return slug, "이미 있는 매뉴얼과 ID 가 같습니다"
    for mid in ids:
        if slug.startswith(mid + "-") or slug.endswith("-" + mid):
            return mid, "파일 이름이 이 매뉴얼을 가리킵니다"
    tkey = re.sub(r"[^a-z0-9]", "", (title or "").lower())
    for m in existing:
        if tkey and tkey == re.sub(r"[^a-z0-9]", "", (m.get("title") or "").lower()):
            return m["id"], "매뉴얼 이름이 같습니다"
    return slug, ""


def _summary(parsed: dict, filename: str, existing: list[dict]) -> dict:
    secs = parsed["sections"]
    title = parsed["title"] or Path(filename).stem
    guess_id, why = _guess_id(filename, title, existing)
    steps = [st for s in secs for b in s["blocks"] for st in b["steps"]]
    return {
        "suggestTitle": title,
        "suggestId": guess_id,
        "idReason": why,
        "cover": bool(parsed["title"]),
        "contactNote": parsed.get("contactNote") or "",
        "sections": [
            {"no": s["no"], "title": s["title"], "slides": s["slides"],
             "steps": [st for b in s["blocks"] for st in b["steps"]][:20],
             "stepCount": sum(len(b["steps"]) for b in s["blocks"]),
             "imageCount": sum(len(b["images"]) for b in s["blocks"])}
            for s in secs
        ],
        "slideCount": sum(len(s["slides"]) for s in secs),
        "totalSteps": len(steps),
        "totalImages": sum(len(b["images"]) for s in secs for b in s["blocks"]),
    }


@app.post("/api/preview")
async def preview(file: UploadFile = File(...), _: dict = Depends(require_admin)):
    """읽기만 한다. **아무것도 바꾸지 않는다.**

    올리자마자 덮어쓰면 "이게 맞나" 를 볼 기회가 없다. 먼저 보여주고,
    보고 나서 누르게 한다.
    """
    blob = await _read(file)
    try:
        parsed = parse(blob)
    except Exception as e:  # noqa: BLE001
        log.exception("PPT 읽기 실패")
        raise HTTPException(status_code=400,
                            detail=f"PPT 를 읽지 못했습니다. ({type(e).__name__}) "
                                   "PowerPoint 에서 다시 저장한 뒤 올려 보세요.")
    if not parsed["sections"]:
        raise HTTPException(status_code=400,
                            detail="슬라이드에서 글자를 찾지 못했습니다. "
                                   "그림으로만 된 PPT 는 항목 이름을 만들 수 없습니다.")
    existing = mio.list_manuals()
    out = _summary(parsed, file.filename or "", existing)
    out["existing"] = existing
    return out


@app.post("/api/apply")
async def apply(file: UploadFile = File(...),
                manual_id: str = Form(...),
                title: str = Form(""),
                icon: str = Form(""),
                subtitle: str = Form(""),
                user: dict = Depends(require_admin)):
    """실제로 매뉴얼을 갈아 끼운다. 되돌릴 수 있도록 먼저 백업한다."""
    mid = (manual_id or "").strip().lower()
    if not mio.valid_id(mid):
        raise HTTPException(status_code=400,
                            detail="매뉴얼 ID 는 영문 소문자·숫자·하이픈만 쓸 수 있습니다. "
                                   "(예: sap-gui)")
    blob = await _read(file)
    try:
        parsed = parse(blob)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"PPT 를 읽지 못했습니다. ({type(e).__name__})")

    kept = mio.backup()
    n_img = mio.write_images(mid, parsed["sections"])
    how = mio.upsert(mid, (title or parsed["title"] or mid).strip(),
                     icon.strip(), subtitle.strip(), parsed["sections"],
                     parsed.get("contactNote") or "")

    n_sec = len(parsed["sections"])
    detail = (f"{mid} · {'교체' if how == 'replaced' else '추가'} · "
              f"항목 {n_sec}개 · 그림 {n_img}장 · 원본 {file.filename}")
    log.info("매뉴얼 갱신 | user=%s %s", user["id"], detail)
    await portal.send_audit("매뉴얼 갱신", user, detail)

    mio.save_source(mid, file.filename or "", blob)

    return {"ok": True, "how": how, "id": mid,
            "sections": n_sec, "images": n_img, "backup": kept}


@app.get("/api/source/{manual_id}")
def source(manual_id: str, _: dict = Depends(require_admin)):
    """그 매뉴얼을 만든 PPT 를 내려받는다.

    고칠 일이 생기면 이걸 받아 고쳐서 다시 올리면 된다. 원본을 찾아
    헤매지 않아도 되고, 만든 사람이 자리에 없어도 이어서 할 수 있다.
    """
    mid = (manual_id or "").strip().lower()
    if not mio.valid_id(mid):
        raise HTTPException(status_code=400, detail="매뉴얼 ID 가 올바르지 않습니다.")
    src = mio.source_of(mid)
    if not src:
        raise HTTPException(status_code=404,
                            detail="이 매뉴얼의 PPT 원본이 없습니다. "
                                   "이 앱을 쓰기 전에 만든 매뉴얼이거나, 손으로 만든 것입니다. "
                                   "PPT 를 한 번 올리면 그때부터 여기 남습니다.")
    return FileResponse(src["path"], filename=src["name"],
                        media_type="application/vnd.openxmlformats-officedocument."
                                   "presentationml.presentation")


@app.delete("/api/manuals/{manual_id}")
async def delete_manual(manual_id: str, user: dict = Depends(require_admin)):
    """매뉴얼 하나를 지운다. 지우기 전에 백업을 뜬다."""
    mid = (manual_id or "").strip().lower()
    if not mio.valid_id(mid):
        raise HTTPException(status_code=400, detail="매뉴얼 ID 가 올바르지 않습니다.")
    if not mio.remove(mid):
        raise HTTPException(status_code=404, detail="그런 매뉴얼이 없습니다.")
    log.info("매뉴얼 삭제 | user=%s %s", user["id"], mid)
    await portal.send_audit("매뉴얼 삭제", user, mid)
    return {"ok": True, "id": mid}
