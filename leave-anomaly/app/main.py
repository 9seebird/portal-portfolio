"""휴가 이상감지 · FastAPI 서버.

사내 포털 아래 /leave-anomaly/ 경로로 붙는 것을 전제로 만들었다.
화면(HTML)과 데이터 통로(REST API)를 분리했고, 화면에서 API 를 부를 때는 항상 상대경로를 쓴다.
"""

from __future__ import annotations

import logging
import re
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, portal
from .analyzer import analyze_all
from .auth import current_user, require_user
from .config import ANOMALY_CONFIG, MAX_UPLOAD_BYTES
from .holidays import OFFICIAL_HOLIDAYS
from .parsers import UploadError, normalize_accrual, normalize_usage, read_table

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("leave-anomaly")

STATIC_DIR = Path(__file__).parent / "static"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """앱이 뜰 때 DB 를 만들고 포털에 자기 자신을 등록한다."""
    db.init_db()
    await portal.register_service()
    yield


app = FastAPI(title="휴가 이상감지", version="1.0.0", lifespan=lifespan,
              docs_url="/docs", redoc_url=None)


@app.exception_handler(UploadError)
async def upload_error_handler(_: Request, exc: UploadError):
    """업로드 검증 실패를 사람이 읽을 수 있는 메시지로 돌려준다."""
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# 기본 확인용
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    """앱이 정상으로 켜졌는지 확인한다. 로그인 없이 호출할 수 있다."""
    return {"ok": True, "service": portal.SERVICE_ID, "version": "1.0.0"}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    """지금 접속한 사람의 이름·부서·권한을 알려준다. 화면에서 버튼 표시를 결정할 때 쓴다."""
    return user


@app.get("/api/criteria")
def criteria(_: dict = Depends(current_user)):
    """감지 기준(가중치표·등급 임계값·저사용/급증 조건)을 그대로 알려준다.

    "휴가 이상감지는 무슨 기준으로 잡아?" 같은 질문에 답할 수 있다.
    """
    return ANOMALY_CONFIG


# ---------------------------------------------------------------------------
# 휴일
# ---------------------------------------------------------------------------
def _holiday_keys() -> set:
    """법정 공휴일 + 회사 자체 휴일 날짜 집합."""
    keys = set(OFFICIAL_HOLIDAYS.keys())
    keys |= {h["date"] for h in db.list_company_holidays()}
    return keys


@app.get("/api/holidays")
def get_holidays(_: dict = Depends(current_user)):
    """고립 판정에 쓰는 휴일 목록(법정 공휴일 + 회사 자체 휴일)을 알려준다."""
    return {"official": OFFICIAL_HOLIDAYS, "company": db.list_company_holidays()}


@app.post("/api/holidays")
async def add_holiday(payload: dict, user: dict = Depends(require_user)):
    """회사 자체 휴일(창립기념일 등)을 등록한다. 접속한 사람은 누구나 가능."""
    date_key = str(payload.get("date", "")).strip()
    name = str(payload.get("name", "")).strip()
    if not DATE_RE.match(date_key) or not name:
        raise HTTPException(status_code=400, detail="날짜(YYYY-MM-DD)와 이름을 모두 입력해 주세요.")
    db.upsert_company_holiday(date_key, name, user)
    db.write_audit(user, "회사휴일 등록", f"{date_key} {name}")
    await portal.send_audit("회사휴일 등록", user, f"{date_key} {name}")
    return {"ok": True, "company": db.list_company_holidays()}


@app.delete("/api/holidays/{date_key}")
async def remove_holiday(date_key: str, user: dict = Depends(require_user)):
    """회사 자체 휴일을 지운다. 접속한 사람은 누구나 가능."""
    if not db.delete_company_holiday(date_key):
        raise HTTPException(status_code=404, detail="해당 날짜의 회사휴일이 없습니다.")
    db.write_audit(user, "회사휴일 삭제", date_key)
    await portal.send_audit("회사휴일 삭제", user, date_key)
    return {"ok": True, "company": db.list_company_holidays()}


# ---------------------------------------------------------------------------
# 데이터 업로드
# ---------------------------------------------------------------------------
@app.get("/api/datasets")
def datasets(_: dict = Depends(require_user)):
    """지금 올라와 있는 사용내역·발생내역이 무엇인지(파일명·건수·업로드 시각) 알려준다."""
    out = {}
    for kind in ("usage", "accrual"):
        data = db.get_dataset(kind)
        out[kind] = None if not data else {
            "filename": data["filename"], "rowCount": data["rowCount"],
            "uploadedAt": data["uploadedAt"], "uploader": data["uploader"],
        }
    return out


@app.post("/api/datasets/{kind}")
async def upload_dataset(kind: str, file: UploadFile = File(...), user: dict = Depends(require_user)):
    """연차 사용내역(usage) 또는 발생내역(accrual) 엑셀을 올린다.

    확장자·PK 시그니처·실제 열 구성까지 확인해 잘못된 파일을 걸러낸다. 접속한 사람은 누구나 가능.
    """
    if kind not in ("usage", "accrual"):
        raise HTTPException(status_code=404, detail="usage 또는 accrual 만 가능합니다.")
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="파일이 너무 큽니다(최대 20MB).")

    rows = read_table(content, file.filename or "")
    parsed = normalize_usage(rows) if kind == "usage" else normalize_accrual(rows)

    safe_name = Path(file.filename or "upload.xlsx").name
    stored = db.UPLOAD_DIR / f"{kind}-{uuid.uuid4().hex[:8]}-{safe_name}"
    stored.write_bytes(content)

    old = db.get_dataset(kind)
    if old:
        Path(old["storedPath"]).unlink(missing_ok=True)
    db.save_dataset(kind, safe_name, str(stored), parsed, user)
    db.write_audit(user, "파일 업로드", f"{kind} · {safe_name} · {len(parsed)}건")
    await portal.send_audit("파일 업로드", user, f"{kind} · {safe_name} · {len(parsed)}건")
    return {"ok": True, "kind": kind, "filename": safe_name, "rowCount": len(parsed)}


@app.delete("/api/datasets/{kind}")
async def remove_dataset(kind: str, user: dict = Depends(require_user)):
    """올린 데이터를 지운다. 접속한 사람은 누구나 가능(이 앱의 접근 정책상 권한 구분 없음)."""
    if kind not in ("usage", "accrual"):
        raise HTTPException(status_code=404, detail="usage 또는 accrual 만 가능합니다.")
    if not db.delete_dataset(kind):
        raise HTTPException(status_code=404, detail="지울 데이터가 없습니다.")
    db.write_audit(user, "데이터 삭제", kind)
    await portal.send_audit("데이터 삭제", user, kind)
    return {"ok": True}


# ---------------------------------------------------------------------------
# 분석 결과
# ---------------------------------------------------------------------------
@app.get("/api/analysis")
def analysis(ref: str | None = None, _: dict = Depends(require_user)):
    """올려둔 데이터로 이상 패턴·저사용·급증 세 가지를 한 번에 계산해 돌려준다.

    ref(기준일, YYYY-MM-DD)를 바꾸면 저사용·급증 계산 시점이 달라진다.
    "고립 연차가 반복되는 사람", "연차를 안 쓰고 쌓아두는 사람", "최근 몰아 쓴 사람"을 걸러낼 수 있다.
    """
    ref_key = ref or date.today().isoformat()
    if not DATE_RE.match(ref_key):
        raise HTTPException(status_code=400, detail="기준일 형식은 YYYY-MM-DD 입니다.")
    usage = db.get_dataset("usage")
    accrual = db.get_dataset("accrual")
    result = analyze_all(
        usage["rows"] if usage else [],
        accrual["rows"] if accrual else [],
        ref_key,
        _holiday_keys(),
    )
    result["meta"] = {
        "usage": None if not usage else {"filename": usage["filename"], "rowCount": usage["rowCount"], "uploadedAt": usage["uploadedAt"]},
        "accrual": None if not accrual else {"filename": accrual["filename"], "rowCount": accrual["rowCount"], "uploadedAt": accrual["uploadedAt"]},
    }
    return result


@app.get("/api/audit")
def audit(limit: int = 100, _: dict = Depends(require_user)):
    """이 앱에서 누가 언제 무엇을 올리고 지웠는지 최근 기록을 보여준다."""
    return {"rows": db.list_audit(min(max(limit, 1), 500))}


# ---------------------------------------------------------------------------
# 화면
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    """메인 화면(HTML)."""
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
