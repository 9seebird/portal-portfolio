"""IT 안내 화면들의 내용을 서버에 담아 둔다.

체크리스트와 ITO 비용처리는 화면 안에 내용이 박혀 있었다. 고치려면
파일을 내려받아 서버에 덮어써야 했고, 그래서 **서버에 파일을 올릴 수
있는 사람 한 명만** 고칠 수 있었다. 그 사람이 없으면 아무도 못 고친다.

이 앱은 그 내용만 맡는다. 화면은 그대로 nginx 가 준다.

  GET  /api/me                 나는 누구고 고칠 수 있는가
  GET  /api/doc                지금 내용
  PUT  /api/doc                내용 저장 (담당자만)
  GET  /api/doc/history        지난 판 목록 (담당자만)
  GET  /api/doc/history/{id}   지난 판 내용 (담당자만)
  POST /api/doc/restore/{id}   그 판으로 되돌리기 (담당자만)
  GET  /healthz                살아 있는지

어느 문서인지는 경로가 아니라 nginx 가 넣어 주는 X-Doc-Key 로 정한다.
(이유는 auth.py 참고)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from . import db, portal
from .auth import doc_key, require_manager, require_user

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("guide-api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    log.info("guide-api 시작. 문서 저장소 준비 완료.")
    yield


app = FastAPI(title="IT 안내 내용 저장소", lifespan=lifespan, docs_url=None, redoc_url=None)


class DocIn(BaseModel):
    data: dict | list
    # 내가 보고 있던 판. 그사이 남이 저장했으면 막는다.
    # 처음 심을 때(서버가 비었을 때)는 없이 보낸다.
    base_version: int | None = None


@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    return "ok"


@app.get("/api/me")
def me(request: Request, user: dict = Depends(require_user)):
    return {**user, "can_edit": user["role"] == "admin", "doc": doc_key(request)}


@app.get("/api/doc")
def read_doc(request: Request, _user: dict = Depends(require_user)):
    key = doc_key(request)
    doc = db.get(key)
    if not doc:
        # 아직 아무도 저장한 적이 없다. 화면이 자기 안의 기본값을 쓰고,
        # 담당자면 그것을 그대로 한 번 저장한다.
        return {"empty": True, "version": 0}
    return {"empty": False, **doc}


@app.put("/api/doc")
async def write_doc(request: Request, body: DocIn, user: dict = Depends(require_manager)):
    key = doc_key(request)
    try:
        doc = db.save(key, body.data, user["id"], body.base_version)
    except db.Conflict as exc:
        # 화면이 이 응답을 보고 "다른 사람이 먼저 고쳤습니다" 라고 알린다.
        return JSONResponse(
            status_code=409,
            content={"detail": "다른 사람이 먼저 저장했습니다. 새로고침해서 확인해 주세요.",
                     "current": exc.current},
        )
    await portal.send_audit(key, "내용 수정", user, f"판 {doc['version']}")
    return doc


@app.get("/api/doc/history")
def read_history(request: Request, _user: dict = Depends(require_manager)):
    return {"items": db.history(doc_key(request))}


@app.get("/api/doc/history/{hid}")
def read_history_item(hid: int, request: Request, _user: dict = Depends(require_manager)):
    data = db.history_data(doc_key(request), hid)
    if data is None:
        raise HTTPException(status_code=404, detail="그 판이 없습니다.")
    return {"data": data}


@app.post("/api/doc/restore/{hid}")
async def restore(hid: int, request: Request, user: dict = Depends(require_manager)):
    """지난 판으로 되돌린다.

    지난 판을 지우고 돌아가는 것이 아니라, **그 내용을 새 판으로 얹는다.**
    되돌린 것 자체도 이력에 남아야 나중에 다시 되짚을 수 있다.
    """
    key = doc_key(request)
    data = db.history_data(key, hid)
    if data is None:
        raise HTTPException(status_code=404, detail="그 판이 없습니다.")
    cur = db.get(key)
    doc = db.save(key, data, user["id"], cur["version"] if cur else None)
    await portal.send_audit(key, "이전 판으로 되돌림", user, f"→ 판 {doc['version']}")
    return doc
