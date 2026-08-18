"""앱 입고 점검 — 앱을 포털에 붙이기 전에 규칙에 맞는지 확인해 준다.

왜 만들었나
──────────
다른 부서에서 만든 앱을 받으면 담당자가 점검 스크립트를 돌려 보고, ✗ 가 있으면
알려 주고, 고쳐서 다시 받고를 반복했다. 오가는 횟수만큼 시간이 든다.
**만든 사람이 스스로 돌려 볼 수 있게 하면 그 왕복이 사라진다.**

체험판에서는 올리기를 받지 않는다
────────────────────────────────
이 앱은 이 포털에서 유일하게 **남이 준 파일을 서버에서 푸는** 앱이다.
공개된 곳에 그 길을 열어 둘 이유가 없어서, 미리 넣어 둔 예시 셋 중에서 고르게 한다.

예시도 **zip 으로 두었다.** 폴더로 두면 두 가지가 나빠진다 —
검사기가 이 앱을 검사할 때 안에 든 「일부러 틀린 예시」까지 같이 잡고,
예시만 다른 코드 길로 들어가서 「예시에서는 되는데」가 생긴다.
지금은 예시도 올린 파일과 **글자 그대로 같은 함수**를 지난다.

사내에서는 DEMO_MODE=0 으로 두고 그대로 올려서 쓴다.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import portal
from .auth import require_user
from .checker import BadZip, run

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("intake")

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
DEMO = str(os.getenv("DEMO_MODE", "0")).strip().lower() in ("1", "true", "yes", "on")
STATIC = Path(__file__).parent / "static"
SAMPLES = Path(os.getenv("SAMPLES_DIR", "/app/samples"))

# 예시 셋. **일부러 하나는 깨끗하고, 하나는 엉망이고, 하나는 그 사이다.**
# 전부 통과하는 예시만 두면 이 도구가 무엇을 잡아내는지 안 보인다.
SAMPLES_META = [
    {"id": "회의실예약", "label": "규칙대로 만든 앱",
     "hint": "포털 헤더를 읽고, 자기 등록을 하고, 주소는 상대경로. 통과합니다."},
    {"id": "출입증관리", "label": "로그인을 스스로 만든 앱",
     "hint": "잘 만든 것 같지만 로그인을 따로 만들었습니다. 포털 권한과 두 겹이 됩니다."},
    {"id": "비품신청", "label": "여기저기 틀린 앱",
     "hint": "바깥 포트를 열고, 떠다니는 태그를 쓰고, 주소가 절대경로입니다."},
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    await portal.register_service()
    yield


app = FastAPI(title="앱 입고 점검", lifespan=lifespan)


@app.get("/api/health")
async def health() -> dict:
    """살아 있는지 확인하는 주소 (규칙 4)."""
    return {"ok": True, "service": portal.SERVICE_ID}


@app.get("/api/mode")
async def mode() -> dict:
    """화면이 올리기 칸을 그릴지 예시 목록을 그릴지 이 값으로 정한다."""
    return {"demo": DEMO, "samples": SAMPLES_META if DEMO else [],
            "max_upload_mb": MAX_UPLOAD_MB}


@app.post("/api/check/{sample_id}")
async def check_sample(sample_id: str, user: dict = Depends(require_user)):
    """미리 넣어 둔 예시 하나를 검사한다."""
    meta = next((s for s in SAMPLES_META if s["id"] == sample_id), None)
    if not meta:
        raise HTTPException(404, "그런 예시가 없습니다.")
    # ★ 목록에 있는 이름만 받는다. 경로를 그대로 이어 붙이면
    #   ../../ 같은 것으로 폴더 밖을 검사시킬 수 있다.
    path = SAMPLES / f'{meta["id"]}.zip'
    if not path.is_file():
        raise HTTPException(500, "예시 파일이 없습니다.")
    result = await run(path.read_bytes(), path.name)
    result["name"] = meta["label"]
    result["sample"] = meta
    await portal.send_audit("입고 점검(예시)", user, meta["label"])
    return JSONResponse(result)


@app.post("/api/check")
async def check_upload(file: UploadFile = File(...), user: dict = Depends(require_user)):
    """올린 zip 하나를 검사한다. 결과만 돌려주고 파일은 남기지 않는다."""
    if DEMO:
        raise HTTPException(
            403, "체험판에서는 파일을 올릴 수 없습니다. 아래 예시 중에서 골라 보세요.")

    data = await file.read()
    size_mb = len(data) / 1024 / 1024
    if size_mb > MAX_UPLOAD_MB:
        raise HTTPException(413, f"파일이 너무 큽니다 ({size_mb:.0f}MB). {MAX_UPLOAD_MB}MB까지만 받습니다.")
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

    t = result["tally"]
    await portal.send_audit("입고 점검", user,
                            f"{result['name']} — ✓{t['ok']} △{t['warn']} ✗{t['bad']}")
    return JSONResponse(result)


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
