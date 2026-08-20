"""온라인 교육 이수 · FastAPI 서버.

챗 포털 아래 /edu/ 경로로 붙는 것을 전제로 만들었다.
화면(HTML)과 데이터 통로(REST API)를 분리했고, 화면에서 API 를 부를 때는 항상 상대경로를 쓴다.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import unicodedata
import urllib.parse
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse

from . import auth, db, portal, roster_file
from .auth import current_user, require_admin, require_user
from .config import (ADMIN_IDS, ALLOWED_EXTENSIONS, AUTH_MODE, BUCKET_SEC,
                     DEFAULT_MIN_RATIO, DEFAULT_PASSWORD, LESSON_KINDS, MAX_UPLOAD_BYTES,
                     MAX_UPLOAD_MB, PASSWORD_MIN_LEN, PDF_MAGIC, PING_INTERVAL_SEC,
                     SERVICE_ID, SERVICE_NAME)

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("edu")

STATIC_DIR = Path(__file__).parent / "static"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(_: FastAPI):
    """앱이 뜰 때 DB 를 만들고 포털에 자기 자신을 등록한다."""
    db.init_db()
    await portal.register_service()
    if auth.standalone():
        log.info("단독 모드로 뜹니다 (AUTH_MODE=%s). 사번·이름으로 로그인합니다.", AUTH_MODE)
        if not db.count_admins() and not ADMIN_IDS:
            log.warning("교육 담당자가 아직 없습니다. .env 의 ADMIN_IDS 에 본인 사번을 넣고 "
                        "다시 띄우면 관리자 화면에 들어갈 수 있습니다.")
    yield


app = FastAPI(title=SERVICE_NAME, version=VERSION, lifespan=lifespan,
              docs_url="/docs", redoc_url=None)


# ---------------------------------------------------------------------------
# 화면
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def page_index():
    """직원 화면. 지정된 과정과 내 진도를 보여준다."""
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/admin", include_in_schema=False)
def page_admin():
    """담당자 화면. 과정 편집과 이수 현황, 대상자 명단 관리."""
    return FileResponse(STATIC_DIR / "admin.html", headers={"Cache-Control": "no-store"})


@app.get("/login", include_in_schema=False)
def page_login():
    """로그인 화면. 단독 모드에서만 쓴다.

    포털 뒤에 놓았을 때는 포털이 이미 확인했으므로 이 화면이 필요 없다.
    (회사 표준 규칙 7 — 포털 모드에서는 로그인 화면을 만들지 않는다)
    """
    if not auth.standalone():
        return RedirectResponse("./", status_code=302)
    return FileResponse(STATIC_DIR / "login.html", headers={"Cache-Control": "no-store"})


@app.post("/api/login")
def do_login(payload: dict, request: Request, response: Response):
    """아이디(또는 사번)와 비밀번호를 확인해 로그인시킨다. 단독 모드에서만 쓴다."""
    if not auth.standalone():
        raise HTTPException(status_code=400, detail="포털을 통해 접속해 주세요.")
    ip = request.headers.get("X-Real-IP") or (request.client.host if request.client else "")
    user = auth.login(str(payload.get("userId", "")), str(payload.get("password", "")), ip)
    auth.set_session(response, user["id"])
    db.write_audit(user, "로그인", "")
    return user


@app.post("/api/me/password")
def change_my_password(payload: dict, user: dict = Depends(require_user)):
    """본인 비밀번호를 바꾼다. 지금 비밀번호를 맞게 넣어야 한다."""
    if not auth.standalone():
        raise HTTPException(status_code=400, detail="비밀번호는 챗 포털에서 바꿔 주세요.")
    auth.change_password(user["id"], str(payload.get("current", "")), str(payload.get("next", "")))
    db.write_audit(user, "비밀번호 변경", "")
    return {"ok": True}


@app.post("/api/logout")
def do_logout(response: Response):
    """로그아웃한다."""
    auth.clear_session(response)
    return {"ok": True}


# ---------------------------------------------------------------------------
# 기본 확인용
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    """앱이 정상으로 켜졌는지 확인한다. 로그인 없이 호출할 수 있다."""
    return {"ok": True, "service": SERVICE_ID, "version": VERSION}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    """지금 접속한 사람의 이름·부서·권한을 알려준다. 화면에서 버튼 표시를 결정할 때 쓴다."""
    return user


@app.get("/api/config")
def client_config(_: dict = Depends(current_user)):
    """화면이 알아야 할 값(진도 보고 주기·칸 크기·기본 이수 기준)을 내려준다."""
    return {"pingInterval": PING_INTERVAL_SEC, "bucketSec": BUCKET_SEC,
            "defaultMinRatio": DEFAULT_MIN_RATIO, "maxUploadMB": MAX_UPLOAD_MB,
            "standalone": auth.standalone(), "authMode": AUTH_MODE,
            "portalAvailable": bool(portal._portal_url()),
            "passwordMinLen": PASSWORD_MIN_LEN}


# ---------------------------------------------------------------------------
# 직원 화면용
# ---------------------------------------------------------------------------
def _days_left(deadline: str | None) -> int | None:
    """마감까지 남은 날. 오늘이 마감이면 0, 지났으면 음수."""
    if not deadline or not DATE_RE.match(deadline):
        return None
    y, m, d = (int(x) for x in deadline.split("-"))
    return (date(y, m, d) - date.today()).days


def _lesson_public(lesson: dict, prog: dict | None) -> dict:
    """차시 하나를 화면이 쓰기 좋은 모양으로. 진도가 있으면 함께 담는다."""
    dur = int(lesson["duration_sec"] or 0)
    covered = int((prog or {}).get("covered_sec") or 0)
    ratio = min(1.0, covered / dur) if dur else 0.0
    return {
        "id": int(lesson["id"]), "seq": lesson["seq"], "title": lesson["title"],
        "kind": lesson["kind"], "youtubeId": lesson["youtube_id"], "url": lesson["url"],
        "note": lesson["note"], "durationSec": dur,
        "minRatio": lesson["min_ratio"] if lesson["min_ratio"] is not None else DEFAULT_MIN_RATIO,
        "required": bool(lesson["required"]),
        "coveredSec": covered,
        "percent": round(ratio * 100),
        "resumeSec": db.resume_at(prog, dur),
        "completed": bool((prog or {}).get("completed")),
        "completedAt": (prog or {}).get("completed_at"),
    }


def _course_public(course: dict, user_id: str) -> dict:
    """과정 하나 + 그 사람의 진도."""
    lessons = db.list_lessons(int(course["id"]))
    pmap = db.progress_map(user_id, int(course["id"]))
    items = [_lesson_public(l, pmap.get(int(l["id"]))) for l in lessons]
    req = [i for i in items if i["required"]]
    done = [i for i in req if i["completed"]]
    return {
        "id": int(course["id"]), "title": course["title"],
        "description": course["description"], "deadline": course["deadline"],
        "daysLeft": _days_left(course["deadline"]),
        "active": bool(course["active"]),
        "lessons": items,
        "doneRequired": len(done), "totalRequired": len(req),
        "completed": bool(req) and len(done) == len(req),
    }


@app.get("/api/courses")
def my_courses(user: dict = Depends(require_user)):
    """나에게 지정된 교육 과정과 내 진도를 한 번에 알려준다.

    "내가 들어야 할 교육이 뭐가 남았나"에 답할 수 있다.
    """
    return {"courses": [_course_public(c, user["id"])
                        for c in db.list_courses(only_active=True)]}


@app.get("/api/status")
def my_status(request: Request, user: dict = Depends(current_user)):
    """지금 접속한 사람의 교육 이수 상태를 한 문장으로 요약해 준다.

    챗에서 "나 교육 다 들었어?" 라고 물었을 때 이 API 가 불린다.
    """
    courses = [_course_public(c, user["id"]) for c in db.list_courses(only_active=True)]
    if not courses:
        return {"summary": "지금 지정된 교육 과정이 없습니다.", "courses": []}
    parts = []
    for c in courses:
        left = c["daysLeft"]
        when = "" if left is None else (
            f", 마감 {c['deadline']}" + (f" (D-{left})" if left >= 0 else " (기한 지남)")
        )
        state = "이수 완료" if c["completed"] else f"{c['doneRequired']}/{c['totalRequired']} 차시 완료"
        parts.append(f"{c['title']}: {state}{when}")
    return {"summary": " / ".join(parts),
            "courses": [{"id": c["id"], "title": c["title"], "completed": c["completed"],
                         "doneRequired": c["doneRequired"], "totalRequired": c["totalRequired"],
                         "deadline": c["deadline"], "daysLeft": c["daysLeft"]}
                        for c in courses]}


@app.post("/api/progress")
async def report_progress(payload: dict, user: dict = Depends(require_user)):
    """영상의 현재 재생 위치를 받아 시청한 구간을 기록하고 이수 여부를 판정한다.

    직전 위치와 지금 위치가 정상 재생 범위 안일 때만 그 사이를 시청한 것으로 인정하므로,
    스크롤바를 맨 뒤로 끌어 이수 처리하는 것을 걸러낼 수 있다.
    """
    lesson_id = int(payload.get("lessonId") or 0)
    lesson = db.get_lesson(lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="없는 차시입니다.")
    if lesson["kind"] != "youtube":
        raise HTTPException(status_code=400, detail="영상 차시에서만 진도를 기록합니다.")

    duration = int(float(payload.get("duration") or 0))
    if duration <= 0:
        raise HTTPException(status_code=400, detail="영상 길이를 알 수 없습니다.")
    pos = max(0.0, float(payload.get("position") or 0))
    prev = max(0.0, float(payload.get("prev") or 0))
    pos = min(pos, float(duration))
    prev = min(prev, float(duration))

    db.set_lesson_duration(lesson_id, duration)
    lesson["duration_sec"] = duration
    result = db.record_watch(user, lesson, prev, pos, duration)

    if result["newlyCompleted"]:
        db.write_audit(user, "차시 이수", f"{lesson['title']}")
        await portal.send_audit("교육 차시 이수", user, lesson["title"])
    return result


@app.post("/api/lessons/{lesson_id}/done")
async def mark_lesson_done(lesson_id: int, user: dict = Depends(require_user)):
    """영상이 아닌 차시(사내 자료·바깥 링크)를 열람 완료로 표시한다."""
    lesson = db.get_lesson(lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="없는 차시입니다.")
    if lesson["kind"] == "youtube":
        raise HTTPException(status_code=400, detail="영상 차시는 시청 진도로 자동 판정됩니다.")
    result = db.mark_done(user, lesson)
    if result["newlyCompleted"]:
        db.write_audit(user, "자료 열람 완료", lesson["title"])
        await portal.send_audit("교육 자료 열람", user, lesson["title"])
    return result


@app.get("/files/{name}")
def get_file(name: str, _: dict = Depends(require_user)):
    """업로드된 사내 자료(PDF)를 내려준다. 접속이 확인된 사람만."""
    safe = Path(name).name
    path = db.UPLOAD_DIR / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="파일이 없습니다.")
    # 파일명에 한글이 들어가면 헤더에 그대로 쓸 수 없다(헤더는 latin-1 만 담는다).
    # RFC 5987 방식으로 인코딩해서 넣는다.
    disp = "inline; filename*=UTF-8''" + urllib.parse.quote(safe)
    return FileResponse(path, media_type="application/pdf",
                        headers={"Content-Disposition": disp})


# ---------------------------------------------------------------------------
# 담당자 화면용
# ---------------------------------------------------------------------------
YT_PATTERNS = [
    re.compile(r"(?:youtu\.be/)([A-Za-z0-9_-]{11})"),
    re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|live/|shorts/))([A-Za-z0-9_-]{11})"),
    re.compile(r"^([A-Za-z0-9_-]{11})$"),
]


def parse_youtube_id(raw: str) -> str | None:
    """유튜브 주소를 붙여 넣어도 영상 ID 만 뽑아낸다. 담당자가 ID 를 직접 찾지 않아도 되게."""
    s = (raw or "").strip()
    if not s:
        return None
    for pat in YT_PATTERNS:
        m = pat.search(s)
        if m:
            return m.group(1)
    return None


@app.get("/api/admin/courses")
def admin_courses(_: dict = Depends(require_admin)):
    """모든 과정을 차시 수와 함께 알려준다(공개되지 않은 것 포함)."""
    out = []
    for c in db.list_courses():
        lessons = db.list_lessons(int(c["id"]))
        out.append({
            "id": int(c["id"]), "title": c["title"], "description": c["description"],
            "deadline": c["deadline"], "daysLeft": _days_left(c["deadline"]),
            "active": bool(c["active"]), "lessonCount": len(lessons),
            "requiredCount": sum(1 for l in lessons if l["required"]),
            "lessons": [_lesson_public(l, None) for l in lessons],
        })
    return {"courses": out}


@app.post("/api/admin/courses")
async def admin_create_course(payload: dict, user: dict = Depends(require_admin)):
    """교육 과정을 새로 만든다. 담당자만 가능."""
    title = str(payload.get("title", "")).strip()
    if not title:
        raise HTTPException(status_code=400, detail="과정 이름을 입력해 주세요.")
    deadline = str(payload.get("deadline", "")).strip()
    if deadline and not DATE_RE.match(deadline):
        raise HTTPException(status_code=400, detail="마감일은 YYYY-MM-DD 형식으로 입력해 주세요.")
    cid = db.create_course(title, str(payload.get("description", "")).strip(),
                           deadline, 1 if payload.get("active", True) else 0)
    db.write_audit(user, "과정 생성", title)
    await portal.send_audit("교육 과정 생성", user, title)
    return {"ok": True, "id": cid}


@app.patch("/api/admin/courses/{course_id}")
async def admin_update_course(course_id: int, payload: dict, user: dict = Depends(require_admin)):
    """과정의 이름·설명·마감일·공개 여부를 고친다. 담당자만 가능."""
    if not db.get_course(course_id):
        raise HTTPException(status_code=404, detail="없는 과정입니다.")
    fields = {}
    for k in ("title", "description", "deadline"):
        if k in payload:
            fields[k] = str(payload[k]).strip()
    if fields.get("deadline") and not DATE_RE.match(fields["deadline"]):
        raise HTTPException(status_code=400, detail="마감일은 YYYY-MM-DD 형식으로 입력해 주세요.")
    if "active" in payload:
        fields["active"] = 1 if payload["active"] else 0
    if not db.update_course(course_id, fields):
        raise HTTPException(status_code=400, detail="고칠 내용이 없습니다.")
    db.write_audit(user, "과정 수정", f"#{course_id}")
    await portal.send_audit("교육 과정 수정", user, f"#{course_id}")
    return {"ok": True}


@app.delete("/api/admin/courses/{course_id}")
async def admin_delete_course(course_id: int, user: dict = Depends(require_admin)):
    """과정을 차시·진도까지 함께 지운다. 되돌릴 수 없으므로 담당자만 가능."""
    course = db.get_course(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="없는 과정입니다.")
    db.delete_course(course_id)
    db.write_audit(user, "과정 삭제", course["title"])
    await portal.send_audit("교육 과정 삭제", user, course["title"])
    return {"ok": True}


def _lesson_payload(payload: dict) -> dict:
    """화면이 보낸 차시 내용을 검사해서 저장할 모양으로 바꾼다."""
    kind = str(payload.get("kind", "youtube")).strip()
    if kind not in LESSON_KINDS:
        raise HTTPException(status_code=400, detail="차시 종류가 올바르지 않습니다.")
    title = str(payload.get("title", "")).strip()
    if not title:
        raise HTTPException(status_code=400, detail="차시 제목을 입력해 주세요.")

    data = {"title": title, "kind": kind,
            "note": str(payload.get("note", "")).strip(),
            "required": 1 if payload.get("required", True) else 0}

    if kind == "youtube":
        vid = parse_youtube_id(str(payload.get("youtubeId") or payload.get("url") or ""))
        if not vid:
            raise HTTPException(
                status_code=400,
                detail="유튜브 주소를 인식하지 못했습니다. 주소창의 주소를 그대로 붙여 넣어 주세요.")
        data["youtube_id"] = vid
        data["url"] = f"https://www.youtube.com/watch?v={vid}"
    else:
        url = str(payload.get("url", "")).strip()
        if not url:
            raise HTTPException(status_code=400, detail="자료 주소(또는 업로드한 파일)를 지정해 주세요.")
        data["url"] = url

    if payload.get("minRatio") not in (None, ""):
        ratio = float(payload["minRatio"])
        if not 0.1 <= ratio <= 1.0:
            raise HTTPException(status_code=400, detail="이수 기준은 0.1 ~ 1.0 사이여야 합니다.")
        data["min_ratio"] = ratio
    if payload.get("seq") not in (None, ""):
        data["seq"] = int(payload["seq"])
    return data


@app.post("/api/admin/courses/{course_id}/lessons")
async def admin_create_lesson(course_id: int, payload: dict, user: dict = Depends(require_admin)):
    """과정에 차시를 추가한다. 유튜브는 주소를 그대로 붙여 넣으면 된다. 담당자만 가능."""
    if not db.get_course(course_id):
        raise HTTPException(status_code=404, detail="없는 과정입니다.")
    data = _lesson_payload(payload)
    lid = db.create_lesson(course_id, data)
    db.write_audit(user, "차시 추가", data["title"])
    return {"ok": True, "id": lid}


@app.patch("/api/admin/lessons/{lesson_id}")
async def admin_update_lesson(lesson_id: int, payload: dict, user: dict = Depends(require_admin)):
    """차시의 제목·주소·순서·이수 기준을 고친다. 담당자만 가능."""
    if not db.get_lesson(lesson_id):
        raise HTTPException(status_code=404, detail="없는 차시입니다.")
    fields: dict = {}
    wiped = 0
    if "seq" in payload:
        fields["seq"] = int(payload["seq"])
    if "required" in payload:
        fields["required"] = 1 if payload["required"] else 0
    if "title" in payload:
        title = str(payload["title"]).strip()
        if not title:
            raise HTTPException(status_code=400, detail="차시 제목을 입력해 주세요.")
        fields["title"] = title
    if "note" in payload:
        fields["note"] = str(payload["note"]).strip()
    if "minRatio" in payload:
        if payload["minRatio"] in (None, ""):
            fields["min_ratio"] = None
        else:
            ratio = float(payload["minRatio"])
            if not 0.1 <= ratio <= 1.0:
                raise HTTPException(status_code=400, detail="이수 기준은 0.1 ~ 1.0 사이여야 합니다.")
            fields["min_ratio"] = ratio
    # 주소는 값이 실제로 들어왔을 때만 건드린다. 빈 칸으로 저장을 누르면
    # 지금 주소를 그대로 두는 것이 사람이 기대하는 동작이다.
    if str(payload.get("youtubeId") or payload.get("url") or "").strip():
        cur = db.get_lesson(lesson_id)
        merged = _lesson_payload({**payload,
                                  "kind": payload.get("kind") or cur["kind"],
                                  "title": payload.get("title") or cur["title"]})
        fields["url"] = merged.get("url")
        if "youtube_id" in merged:
            fields["youtube_id"] = merged["youtube_id"]
            # 영상이 바뀌면 길이를 다시 재야 하고, 옛 영상에서 쌓인 진도는 버려야 한다.
            # 그대로 두면 안 본 강의가 이수로 잡힌다.
            if merged["youtube_id"] != cur.get("youtube_id"):
                fields["duration_sec"] = 0
                wiped = db.clear_lesson_progress(lesson_id)
    if not db.update_lesson(lesson_id, fields):
        raise HTTPException(status_code=400, detail="고칠 내용이 없습니다.")
    db.write_audit(user, "차시 수정", f"#{lesson_id}"
                   + (f" (영상 교체 · 진도 {wiped}건 초기화)" if wiped else ""))
    return {"ok": True, "progressCleared": wiped}


@app.delete("/api/admin/lessons/{lesson_id}")
async def admin_delete_lesson(lesson_id: int, user: dict = Depends(require_admin)):
    """차시를 그 진도까지 함께 지운다. 되돌릴 수 없으므로 담당자만 가능."""
    lesson = db.get_lesson(lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="없는 차시입니다.")
    db.delete_lesson(lesson_id)
    db.write_audit(user, "차시 삭제", lesson["title"])
    await portal.send_audit("교육 차시 삭제", user, lesson["title"])
    return {"ok": True}


@app.post("/api/admin/upload")
async def admin_upload(file: UploadFile = File(...), user: dict = Depends(require_admin)):
    """사내 자료(PPT 를 PDF 로 변환한 것)를 올린다.

    확장자뿐 아니라 파일 앞머리가 실제로 %PDF- 인지까지 확인해 가짜 파일을 걸러낸다.
    담당자만 가능.
    """
    name = unicodedata.normalize("NFC", Path(file.filename or "").name)
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400,
                            detail=f"PDF 만 올릴 수 있습니다. (받은 파일: {name})")
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400,
                            detail=f"파일이 너무 큽니다. {MAX_UPLOAD_MB}MB 까지만 올릴 수 있습니다.")
    if not content.startswith(PDF_MAGIC):
        raise HTTPException(status_code=400,
                            detail="PDF 파일이 아닙니다. 확장자만 .pdf 로 바꾼 파일일 수 있습니다.")

    stem = re.sub(r"[^0-9A-Za-z가-힣._-]", "_", Path(name).stem)[:60] or "doc"
    stored = f"{stem}_{uuid.uuid4().hex[:8]}.pdf"
    (db.UPLOAD_DIR / stored).write_bytes(content)
    db.write_audit(user, "자료 업로드", f"{name} → {stored}")
    await portal.send_audit("교육 자료 업로드", user, name)
    return {"ok": True, "filename": name, "url": f"files/{stored}"}


@app.post("/api/admin/roster/sync")
async def admin_sync_roster(request: Request, payload: dict | None = None,
                            user: dict = Depends(require_admin)):
    """포털의 직원 명단을 가져와 교육 대상자로 삼는다.

    포털 뒤에 있으면 접속한 관리자의 포털 쿠키를 그대로 쓰고, 단독으로 돌고 있으면
    포털 관리자 아이디·비밀번호를 한 번 받아 로그인한다. **비밀번호는 저장하지 않는다.**
    """
    payload = payload or {}
    token = request.cookies.get("portal_token", "")
    try:
        if token:
            people = await portal.fetch_roster(token)
        else:
            pid = str(payload.get("portalId", "")).strip()
            pw = str(payload.get("portalPassword", ""))
            if not pid or not pw:
                raise portal.RosterError(
                    "포털 관리자 아이디와 비밀번호가 필요합니다. "
                    "포털을 쓰지 않는다면 명단 파일을 올려 주세요.")
            people = await portal.fetch_roster_by_login(pid, pw)
    except portal.RosterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    n = db.replace_roster(people, source="portal")
    fresh = auth.give_default_passwords()
    db.write_audit(user, "대상자 명단 갱신(포털)", f"{n}명 (초기 비밀번호 {fresh}명)")
    await portal.send_audit("교육 대상자 명단 갱신", user, f"포털에서 {n}명")
    return {"ok": True, "count": n, "newPasswords": fresh,
            "syncedAt": db.roster_synced_at(), "source": "portal"}


@app.post("/api/admin/roster/upload")
async def admin_upload_roster(file: UploadFile = File(...), user: dict = Depends(require_admin)):
    """대상자 명단을 CSV·엑셀 파일로 올린다.

    첫 줄에 사번 / 이름 / 부서 열이 있으면 된다. 담당자 열이 있으면 그 사람이
    교육 담당자가 된다. 열 이름은 '사원번호', '성명', '소속' 처럼 달라도 알아본다.
    """
    content = await file.read()
    try:
        people = roster_file.parse(file.filename or "", content)
    except roster_file.RosterFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    n = db.replace_roster(people, source="file")
    # 파일에 담당자 표시가 없고 지금 담당자도 없으면, 올린 사람을 담당자로 남긴다.
    # 그러지 않으면 명단을 올린 순간 관리자 화면에 못 들어가는 일이 생긴다.
    if not db.count_admins():
        db.set_roster_admin(user["id"], True)
    # 새로 들어온 사람에게 초기 비밀번호를 넣어 준다. 이미 바꾼 사람은 건드리지 않는다.
    fresh = auth.give_default_passwords()
    db.write_audit(user, "대상자 명단 업로드", f"{file.filename} · {n}명 (초기 비밀번호 {fresh}명)")
    await portal.send_audit("교육 대상자 명단 업로드", user, f"{n}명")
    return {"ok": True, "count": n, "newPasswords": fresh,
            "syncedAt": db.roster_synced_at(), "source": "file"}


@app.get("/api/admin/roster/template")
def admin_roster_template(_: dict = Depends(require_admin)):
    """명단 파일 양식(CSV)을 내려준다. 이대로 채워서 올리면 된다."""
    rows = [["아이디", "이름", "부서", "사번", "담당자"],
            ["hong", "홍길동", "인사총무팀", "1001", "O"],
            ["kimcs", "김철수", "개발팀", "1002", ""],
            ["leeyh", "이영희", "영업팀", "1003", ""]]
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    data = "\ufeff" + buf.getvalue()
    return StreamingResponse(
        iter([data.encode("utf-8")]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 "attachment; filename*=UTF-8''" + urllib.parse.quote("교육대상자_명단양식.csv")})


@app.post("/api/admin/roster/person")
async def admin_add_person(payload: dict, user: dict = Depends(require_admin)):
    """명단에 한 사람을 더한다. 초기 비밀번호가 함께 만들어진다."""
    uid = str(payload.get("userId", "")).strip()
    name = str(payload.get("name", "")).strip()
    if not uid or not name:
        raise HTTPException(status_code=400, detail="아이디와 이름을 모두 입력해 주세요.")
    if db.get_roster_person(uid):
        raise HTTPException(status_code=400, detail=f"이미 있는 아이디입니다: {uid}")
    emp = str(payload.get("empNo", "")).strip()
    if emp and db.emp_no_taken(emp):
        raise HTTPException(status_code=400, detail=f"다른 사람이 쓰고 있는 사번입니다: {emp}")
    db.upsert_roster_person({"user_id": uid, "emp_no": emp, "name": name,
                             "dept": str(payload.get("dept", "")).strip(),
                             "active": 1, "is_admin": 0, "source": "manual"})
    auth.set_password(uid, DEFAULT_PASSWORD)
    db.write_audit(user, "명단 추가", f"{uid} {name}")
    return {"ok": True, "initialPassword": DEFAULT_PASSWORD}


@app.patch("/api/admin/roster/{user_id}")
async def admin_edit_person(user_id: str, payload: dict, user: dict = Depends(require_admin)):
    """명단의 한 사람을 고친다. 이름·부서·사번·재직 여부를 바꿀 수 있다.

    아이디는 바꾸지 않는다. 아이디가 진도 기록을 잇는 열쇠라, 바꾸면 그동안의
    이수 기록이 끊긴다. 아이디를 바꿔야 하면 지우고 새로 넣는 편이 분명하다.
    """
    person = db.get_roster_person(user_id)
    if not person:
        raise HTTPException(status_code=404, detail="명단에 없는 아이디입니다.")
    emp = str(payload.get("empNo", person.get("emp_no") or "")).strip()
    if emp and db.emp_no_taken(emp, except_user=user_id):
        raise HTTPException(status_code=400, detail=f"다른 사람이 쓰고 있는 사번입니다: {emp}")
    name = str(payload.get("name", person.get("name") or "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="이름은 비워 둘 수 없습니다.")
    active = payload.get("active", person.get("active", 1))
    if not active and person.get("is_admin") and db.count_admins() <= 1:
        raise HTTPException(status_code=400, detail="담당자가 한 명은 있어야 합니다.")
    db.upsert_roster_person({
        "user_id": user_id, "emp_no": emp, "name": name,
        "dept": str(payload.get("dept", person.get("dept") or "")).strip(),
        "active": 1 if active else 0, "is_admin": person.get("is_admin", 0),
        "source": person.get("source") or "manual"})
    db.write_audit(user, "명단 수정", f"{user_id} {name}")
    return {"ok": True}


@app.delete("/api/admin/roster/{user_id}")
async def admin_delete_person(user_id: str, user: dict = Depends(require_admin)):
    """명단에서 한 사람을 지운다. 진도 기록은 남으므로 현황에는 ‘명단 밖’으로 보인다."""
    person = db.get_roster_person(user_id)
    if not person:
        raise HTTPException(status_code=404, detail="명단에 없는 아이디입니다.")
    if person.get("is_admin") and db.count_admins() <= 1:
        raise HTTPException(status_code=400, detail="담당자가 한 명은 있어야 합니다.")
    db.delete_roster_person(user_id)
    db.write_audit(user, "명단 삭제", user_id)
    return {"ok": True}


@app.post("/api/admin/roster/{user_id}/password")
async def admin_reset_password(user_id: str, user: dict = Depends(require_admin)):
    """한 사람의 비밀번호를 초기 비밀번호로 되돌린다. 비밀번호를 잊었을 때 쓴다."""
    if not db.get_roster_person(user_id):
        raise HTTPException(status_code=404, detail="명단에 없는 아이디입니다.")
    auth.set_password(user_id, DEFAULT_PASSWORD)
    db.write_audit(user, "비밀번호 초기화", user_id)
    await portal.send_audit("교육 비밀번호 초기화", user, user_id)
    return {"ok": True, "password": DEFAULT_PASSWORD}


@app.patch("/api/admin/roster/{user_id}/admin")
async def admin_set_roster_admin(user_id: str, payload: dict, user: dict = Depends(require_admin)):
    """명단에서 교육 담당자를 지정하거나 해제한다.

    담당자가 한 명도 없어지면 아무도 관리자 화면에 들어갈 수 없으므로 마지막 한 명은 막는다.
    """
    want = bool(payload.get("isAdmin"))
    if not want and db.count_admins() <= 1:
        raise HTTPException(status_code=400,
                            detail="담당자가 한 명은 있어야 합니다. 다른 사람을 먼저 담당자로 지정해 주세요.")
    if not db.set_roster_admin(user_id, want):
        raise HTTPException(status_code=404, detail="명단에 없는 사번입니다.")
    db.write_audit(user, "담당자 지정" if want else "담당자 해제", user_id)
    return {"ok": True}


@app.get("/api/admin/roster")
def admin_roster(_: dict = Depends(require_admin)):
    """지금 등록된 교육 대상자 명단과 마지막 갱신 시각을 알려준다."""
    people = db.list_roster()
    return {"count": len(people), "syncedAt": db.roster_synced_at(),
            "source": db.roster_source(), "adminCount": db.count_admins(),
            "people": people}


@app.get("/api/admin/stats")
def admin_stats(courseId: int, _: dict = Depends(require_admin)):
    """한 과정의 이수 현황을 알려준다. 이수율, 부서별 집계, 사람별 진도가 모두 들어 있다.

    "교육 이수율 얼마야", "아직 안 들은 사람 누구야" 에 답할 수 있다.
    """
    course = db.get_course(courseId)
    if not course:
        raise HTTPException(status_code=404, detail="없는 과정입니다.")
    rows = db.course_rows(courseId)
    total = len(rows)
    done = sum(1 for r in rows if r["completed"])
    started = sum(1 for r in rows if r["started"] and not r["completed"])

    by_dept: dict[str, dict] = {}
    for r in rows:
        d = by_dept.setdefault(r.get("dept") or "(부서 없음)",
                               {"dept": r.get("dept") or "(부서 없음)", "total": 0, "done": 0})
        d["total"] += 1
        d["done"] += 1 if r["completed"] else 0
    for d in by_dept.values():
        d["percent"] = round(d["done"] / d["total"] * 100) if d["total"] else 0

    lessons = db.list_lessons(courseId)
    lesson_stats = []
    for l in lessons:
        lid = int(l["id"])
        with db.connect() as conn:
            c = conn.execute("SELECT COUNT(*) FROM progress WHERE lesson_id = ? AND completed = 1",
                             (lid,)).fetchone()[0]
        lesson_stats.append({"id": lid, "title": l["title"], "kind": l["kind"],
                             "required": bool(l["required"]), "doneCount": c})

    return {
        "course": {"id": courseId, "title": course["title"], "deadline": course["deadline"],
                   "daysLeft": _days_left(course["deadline"]), "active": bool(course["active"])},
        "summary": {"total": total, "completed": done, "inProgress": started,
                    "notStarted": total - done - started,
                    "percent": round(done / total * 100) if total else 0},
        "byDept": sorted(by_dept.values(), key=lambda x: (x["percent"], x["dept"])),
        "lessons": lesson_stats,
        "people": rows,
        "rosterSyncedAt": db.roster_synced_at(),
    }


@app.get("/api/admin/summary")
def admin_summary(_: dict = Depends(require_admin)):
    """공개 중인 모든 과정의 이수율을 한 문장으로 요약해 준다. 챗에서 물어볼 때 쓴다."""
    out = []
    for c in db.list_courses(only_active=True):
        rows = db.course_rows(int(c["id"]))
        total = len(rows)
        done = sum(1 for r in rows if r["completed"])
        pct = round(done / total * 100) if total else 0
        left = _days_left(c["deadline"])
        when = "" if left is None else (f", D-{left}" if left >= 0 else ", 기한 지남")
        out.append({"id": int(c["id"]), "title": c["title"], "total": total,
                    "completed": done, "percent": pct, "deadline": c["deadline"],
                    "daysLeft": left,
                    "text": f"{c['title']} 이수율 {pct}% ({done}/{total}명{when})"})
    if not out:
        return {"summary": "공개 중인 교육 과정이 없습니다.", "courses": []}
    return {"summary": " / ".join(o["text"] for o in out), "courses": out}


@app.get("/api/admin/export")
def admin_export(courseId: int, status: str = "all", dept: str = "", q: str = "",
                 _: dict = Depends(require_admin)):
    """이수 현황을 엑셀에서 바로 열 수 있는 CSV 로 내려준다.

    status(all|not|none|done)·dept·q 로 걸러서 받을 수 있다.
    '미수강자만' 뽑아 리마인드를 돌릴 때 쓰라고 둔 것이다.
    """
    course = db.get_course(courseId)
    if not course:
        raise HTTPException(status_code=404, detail="없는 과정입니다.")
    rows = db.course_rows(courseId)

    if status == "not":
        rows = [r for r in rows if not r["completed"]]
    elif status == "none":
        rows = [r for r in rows if not r["started"]]
    elif status == "done":
        rows = [r for r in rows if r["completed"]]
    if dept:
        rows = [r for r in rows if (r.get("dept") or "") == dept]
    if q:
        needle = q.strip().lower()
        rows = [r for r in rows
                if any(needle in str(r.get(k) or "").lower()
                       for k in ("id", "empNo", "name", "dept"))]

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["아이디", "사번", "이름", "부서", "이수여부", "완료 차시", "필수 차시",
                "진도(%)", "시청률(%)", "이수일시", "마지막 활동", "명단등록"])
    for r in rows:
        w.writerow([r["id"], r.get("empNo") or "", r.get("name") or "", r.get("dept") or "",
                    "이수" if r["completed"] else ("진행중" if r["started"] else "미시작"),
                    r["doneRequired"], r["totalRequired"], r["percent"], r["watchPercent"],
                    r.get("completedAt") or "", r.get("lastAt") or "",
                    "예" if r.get("inRoster") else "아니오(명단 밖)"])

    # 엑셀이 한글을 깨뜨리지 않도록 BOM 을 붙인다.
    data = "﻿" + buf.getvalue()
    safe = re.sub(r"[^0-9A-Za-z가-힣_-]", "_", course["title"])[:40] or "course"
    tag = {"not": "_미이수", "none": "_미시작", "done": "_이수자"}.get(status, "")
    if dept:
        tag += "_" + re.sub(r"[^0-9A-Za-z가-힣_-]", "_", dept)[:20]
    fname = f"{safe}_이수현황{tag}_{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([data.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 "attachment; filename*=UTF-8''" + urllib.parse.quote(fname)},
    )


@app.get("/api/admin/audit")
def admin_audit(limit: int = 200, _: dict = Depends(require_admin)):
    """이 앱에 남은 최근 이력을 알려준다."""
    limit = max(1, min(1000, limit))
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
                            (limit,)).fetchall()
    return {"logs": [dict(r) for r in rows]}
