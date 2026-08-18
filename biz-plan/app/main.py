# -*- coding: utf-8 -*-
"""사업계획 예상손익 (biz-plan)

재무팀이 쓰던 「사업계획용 예상손익 자료작성.html」을 사내 포털에 붙인 것이다.
화면과 계산 결과는 원본 그대로다. 달라진 것은 **계산하는 자리**뿐이다.

    원본 : 브라우저가 인터넷에서 파이썬을 받아 와 직접 계산
    지금 : 같은 파이썬(app/engine.py)이 이 컨테이너에서 계산

app/engine.py 는 원본 HTML 안에 있던 976줄을 **한 줄도 바꾸지 않고** 옮긴 것이다.
숫자가 달라지면 안 되기 때문이다. 새로 붙인 것은 app/precheck.py 하나로,
계산 규칙이 아니라 **입구 검사**다.

왜 입구 검사가 필요한가 —
이 앱의 위험은 "틀렸는데 표는 멀쩡히 나오는 것"이다. 채널 이름 하나가 어긋나면
그 채널 매출이 통째로 빠지는데 아무 표시가 없다. 실제로 원작자가 준 예시 파일이
9천만 원을 흘리고 있었다(신규채널A). 그래서 결과를 보여 주기 **전에** 확인하고,
걸리면 숫자를 아예 내보내지 않는다.

파일은 저장하지 않는다. 받아서 메모리에서 처리하고 버린다.
"""
from __future__ import annotations

import base64
import binascii
import io
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import engine, portal, precheck
from .auth import require_user, service_call

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("biz-plan")

VERSION = "1.0.0"
HERE = os.path.dirname(__file__)
STATIC = os.path.join(HERE, "static")

# 올릴 수 있는 파일 크기. 예시 파일은 둘 합쳐 0.4MB 이고, 실제 사업계획도
# 이 정도다. 앞단 nginx 에서 한 번 더 막지만 여기서도 본다 —
# nginx 만 믿으면 프록시를 안 거치는 경로에서 뚫린다.
MAX_MB = float(os.getenv("BIZPLAN_MAX_MB", "30"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    await portal.register_service()
    yield


app = FastAPI(title="사업계획 예상손익", version=VERSION, lifespan=lifespan)


# ── 오류를 사람 말로 ─────────────────────────────────────────────
@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    """예상 못 한 오류가 그대로 화면에 나가지 않게 한다.

    파이썬 오류 문구는 원인을 알려 주지 않는다. 'File is not a zip file' 를
    보고 무엇을 해야 할지 아는 사람은 없다. 자세한 것은 로그에만 남긴다.
    """
    log.exception("처리하지 못한 오류: %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "처리 중 문제가 생겼습니다. 담당자에게 알려 주세요."},
    )


def _b64(name: str, data: str) -> bytes:
    """화면이 보낸 base64 를 되돌린다. 크기도 여기서 본다."""
    if not data:
        raise HTTPException(status_code=400, detail=f"{name} 파일이 오지 않았습니다.")
    # base64 는 원본보다 약 4/3 크다
    if len(data) * 3 / 4 > MAX_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"{name} 파일이 너무 큽니다. {MAX_MB:.0f}MB 까지 올릴 수 있습니다.")
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400,
                            detail=f"{name} 파일을 읽지 못했습니다. 다시 올려 주세요.")


def _as_checks(stop, warn, info) -> list[dict]:
    out = [{"level": "stop", "text": t} for t in stop]
    out += [{"level": "warn", "text": t} for t in warn]
    out += [{"level": "ok", "text": t} for t in info]
    return out


# ── 화면 ─────────────────────────────────────────────────────────
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/api/health")
def health():
    return {"ok": True, "version": VERSION}


@app.get("/api/me")
def me(request: Request):
    return require_user(request)


# ── 최초 계산 ────────────────────────────────────────────────────
@app.post("/api/run")
async def run(request: Request, body: dict = Body(...)):
    user = require_user(request)
    base_bytes = _b64("마스터 양식", body.get("base_b64") or "")
    sales_bytes = _b64("매출목표·비용", body.get("sales_b64") or "")

    # ① 엔진을 부르기 전 검사.
    #    여기서 걸리는 것을 엔진에 넘기면 'File is not a zip file' 만 나온다.
    stop, warn, info = precheck.check(base_bytes, sales_bytes)
    if stop:
        return {"checks": _as_checks(stop, warn, info), "data": None}

    # ② 계산 — 원본과 같은 코드
    try:
        result = json.loads(engine.init_report_from_b64(
            base64.b64encode(base_bytes).decode(),
            base64.b64encode(sales_bytes).decode(),
        ))
    except KeyError as exc:
        raise HTTPException(status_code=400,
                            detail=f"파일에서 {exc} 을(를) 찾지 못했습니다. "
                                   "예시 파일과 같은 양식인지 확인해 주세요.")
    except Exception as exc:  # noqa: BLE001
        log.exception("계산 실패")
        raise HTTPException(status_code=400,
                            detail=f"계산하지 못했습니다. 파일 양식을 확인해 주세요. ({type(exc).__name__})")

    # ③ 계산한 뒤에야 알 수 있는 검사 — 합계가 맞는가
    total = result["data"]["annual_total_cg"][0]
    base = engine.load_base(io.BytesIO(base_bytes))
    stop2, warn2, info2 = precheck.check(base_bytes, sales_bytes, base, total)

    checks = _as_checks(stop + stop2, warn + warn2, info + info2)
    await portal.send_audit(
        "예상손익 계산", user,
        f"매출 {total:,.0f}" + (" · 점검에서 멈춤" if stop2 else ""))

    if stop2:
        # 숫자를 아예 안 보낸다. 보내면 사람은 그 표를 믿는다.
        return {"checks": checks, "data": None}
    return {"checks": checks, "data": result["data"], "raw_payload": result["raw_payload"]}


# ── 값을 고친 뒤 다시 계산 ───────────────────────────────────────
@app.post("/api/recompute")
def recompute(request: Request, body: dict = Body(...)):
    require_user(request)
    payload = body.get("payload")
    if not payload:
        raise HTTPException(status_code=400, detail="다시 계산할 값이 오지 않았습니다.")
    try:
        return {"data": json.loads(engine.recompute(json.dumps(payload)))}
    except Exception as exc:  # noqa: BLE001
        log.exception("재계산 실패")
        raise HTTPException(status_code=400,
                            detail=f"다시 계산하지 못했습니다. 고친 값에 숫자가 아닌 것이 "
                                   f"섞이지 않았는지 확인해 주세요. ({type(exc).__name__})")


# ── 엑셀 3개 만들기 ──────────────────────────────────────────────
@app.post("/api/export")
async def export(request: Request, body: dict = Body(...)):
    user = require_user(request)
    payload = body.get("payload")
    if not payload:
        raise HTTPException(status_code=400, detail="내보낼 값이 오지 않았습니다.")
    try:
        files = json.loads(engine.export_files(json.dumps(payload)))
    except Exception as exc:  # noqa: BLE001
        log.exception("엑셀 생성 실패")
        raise HTTPException(status_code=400,
                            detail=f"엑셀을 만들지 못했습니다. ({type(exc).__name__})")
    await portal.send_audit("예상손익 엑셀 내려받기", user, f"{len(files)}개")
    return {"files": files}


# ── 챗 통로 ──────────────────────────────────────────────────────
@app.post("/api/analyze")
async def analyze(request: Request, body: dict = Body(...)):
    """포털 챗이 부른다. 사람이 화면에서 부르는 것과 통로를 나눈다.

    챗에는 **요약만** 준다. 표 전체를 챗에 쏟으면 읽을 수 없고,
    상세는 이 앱 화면에서 보는 것이 맞다.
    """
    if not service_call(request):
        raise HTTPException(status_code=403, detail="포털을 통해 접속해 주세요.")
    user = require_user(request)

    base_bytes = _b64("마스터 양식", body.get("base_b64") or "")
    sales_bytes = _b64("매출목표·비용", body.get("sales_b64") or "")

    stop, warn, info = precheck.check(base_bytes, sales_bytes)
    if stop:
        return {"ok": False, "checks": _as_checks(stop, warn, info)}

    result = json.loads(engine.init_report_from_b64(
        base64.b64encode(base_bytes).decode(),
        base64.b64encode(sales_bytes).decode()))
    d = result["data"]
    total = d["annual_total_cg"][0]
    base = engine.load_base(io.BytesIO(base_bytes))
    stop2, warn2, info2 = precheck.check(base_bytes, sales_bytes, base, total)
    checks = _as_checks(stop + stop2, warn + warn2, info + info2)

    await portal.send_audit("예상손익 계산(챗)", user, f"매출 {total:,.0f}")

    if stop2:
        return {"ok": False, "checks": checks}

    lab = d["pl_labels"]
    t = d["annual_total_cg"]
    return {
        "ok": True,
        "checks": checks,
        "summary": {lab[i]: t[i] for i in (0, 1, 3, 4, 22, 24)},
        "cg_list": d["cg_list"],
        "br_list": d["br_list"],
        "url": "/biz-plan/",
    }
