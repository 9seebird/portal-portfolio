"""포털 백엔드 — 채팅 엔드포인트.

실행:
    uvicorn app.main:app --reload --port 8000
확인:
    http://localhost:8000/
"""

import json
import logging
import os
import secrets
from urllib.parse import quote

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import (Depends, FastAPI, File, Form, Header, HTTPException,
                     Request, Response, UploadFile)
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (access, agent, auth, bulk_users, demo, depts, memory, registry,
               services, uploads, usage, users)
from .auth import admin_user, current_user
from .registry import User

# 도구 등록 — import 하는 것만으로 @tool 데코레이터가 실행된다.
from .tools import (basic, ai_report, biz_plan, file_read, guide,  # noqa: F401
                    it_asset, memory_tools, portal)  # noqa: F401

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

memory.init()
users.init()
services.init()
depts.init()
# 서비스와 부서는 비어 있는 채로 시작한다.
# 실제로 없는 항목이 목록에 떠 있으면 "있는 줄 알고 눌렀는데 없다"가 된다.
# 다만 부서 테이블 도입 전에 만든 계정의 부서는 목록으로 끌어온다.
depts.sync_from_users()
uploads.init()
usage.init()
# 공개 데모용 안전장치. DEMO_MODE=0 이면 아무 일도 하지 않는다.
demo.seed()
# 보관 기간이 지난 기록 정리
memory.purge_old()
uploads.purge_old()
usage.purge_old()

app = FastAPI(title="사내 AI 챗 포털")
# ★ 붙이는 자리가 여기여야 한다. 라우터를 그리기 전에 붙여도 되지만,
#   app 을 만든 직후가 아니면 미들웨어가 요청을 못 받는 경우가 있다.
demo.install(app)
app.mount("/static", StaticFiles(directory="static"), name="static")


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    # 챗 입력창에 붙인 파일들. 내용이 아니라 file_id 만 온다.
    file_ids: list[str] = []


class LoginRequest(BaseModel):
    user_id: str
    password: str


@app.get("/")
def index():
    return FileResponse("static/chat.html")


@app.get("/login")
def login_page():
    return FileResponse("static/login.html")


@app.get("/back.js")
def back_js():
    """앱들이 함께 쓰는 「← 포탈로」 동작.

    앱마다 복사해 두면 한 곳을 고쳐도 나머지는 옛 동작으로 남는다.
    포털이 한 벌만 주고, 앱은 <script src="/back.js" defer> 한 줄만 넣는다.
    로그인 없이도 받을 수 있어야 한다 — 이건 비밀이 아니라 화면 동작이다.
    """
    return FileResponse("static/back.js", media_type="application/javascript")


@app.post("/api/login")
def login(req: LoginRequest, response: Response):
    """아이디·비밀번호 확인 후 JWT 발급.

    토큰을 두 곳에 준다.
      - 응답 본문  : 챗 화면이 헤더에 담아 보낼 용도
      - 쿠키       : /ai-report/ 같은 옆 서비스로 이동했을 때 쓸 용도
    """
    u = users.authenticate(req.user_id.strip(), req.password)
    if not u:
        # 실패 사유를 구분해 알려주지 않는다
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    token, expires_in = auth.issue_token(u)
    auth.set_login_cookie(response, token)
    logging.info("로그인 | user=%s", u["user_id"])
    return {"token": token, "expires_in": expires_in,
            "must_change": bool(u["must_change"]),
            "user": {"user_id": u["user_id"], "name": u["name"],
                     "dept": u["dept"], "is_admin": bool(u["is_admin"])}}


@app.post("/api/logout")
def logout(response: Response):
    """쿠키를 지운다. 챗 화면은 localStorage 도 함께 비운다."""
    auth.clear_login_cookie(response)
    return {"ok": True}


@app.get("/api/demo")
def demo_status(request: Request):
    """체험판인지, 챗이 몇 번 남았는지. 로그인 전에도 봐야 해서 열어 둔다.

    사내(DEMO_MODE=0)에서는 {"demo": false} 만 나가고 화면은 아무것도
    그리지 않는다. 화면 파일을 두 벌로 나누지 않으려는 것이다."""
    return demo.status(request)


@app.get("/health")
def health():
    """배포 확인용. 도커 healthcheck 에서도 이 주소를 쓴다."""
    return {"ok": True}


@app.get("/api/me")
def me(user: User = Depends(current_user)):
    """로그인한 본인 정보 + 사용 가능한 앱 목록.

    앱 목록을 여기서 함께 주는 이유는, 화면에 보이는 목록과
    챗 도구가 쓰는 목록이 같은 판정 함수(access.can_use)를 거치게
    하기 위해서다. 두 곳이 갈라지면 "보이는데 안 된다"가 생긴다.
    """
    apps = access.visible(
        user, services.all_services(include_disabled=False), user.ip
    )
    u = users.get(user.user_id) or {}
    return {
        "user": {"user_id": user.user_id, "name": user.name,
                 "dept": user.dept, "is_admin": user.is_admin,
                 "must_change": bool(u.get("must_change"))},
        "apps": [
            # mine : 관리자 특권을 빼고 봐도 쓸 수 있는 앱인가.
            #        화면의 「내 범위만 보기」가 이 값으로 거른다.
            #        관리자가 아닌 사람에게는 항상 true 다 (안 보이면 목록에 없으니).
            {"id": a["id"], "name": a["name"], "desc": a["description"],
             "url": a["url"], "color": a["color"],
             "mine": access.can_use(user, a, user.ip, as_member=True)}
            for a in apps
        ],
        # ── 옆 서비스(ai-report 등)가 읽는 평평한 형태 ──
        # 기존 포털이 쓰던 이름 그대로 둔다. 그래야 ai-report 쪽 코드를
        # 고치지 않고 PORTAL_API_URL 만 바꾸면 붙는다.
        "logged_in": True,
        "id": user.user_id,
        "name": user.name,
        "dept": user.dept,
        "is_admin": user.is_admin,
    }


@app.get("/api/verify")
def verify(service: str | None = None, user: User = Depends(current_user)):
    """옆 서비스가 "이 사람이 이걸 써도 되나"를 물어보는 자리.

    각 서비스가 자기 명단을 따로 관리하면 관리자 화면에서 접근 범위를
    바꿔도 그쪽은 그대로다. 판정은 여기 한 곳에서만 한다.

        GET /api/verify?service=ai-report
        → {"logged_in":true, "id":"kim", "is_admin":false,
           "allowed":true,     쓸 수 있는가 (조회·업로드)
           "manage":false}     관리할 수 있는가 (삭제처럼 되돌릴 수 없는 것)

    두 가지를 나눠서 돌려준다. 부서 전체가 리포트를 볼 수 있어도
    남이 올린 파일을 지우는 건 담당자만 할 수 있어야 한다.
    """
    out = {"logged_in": True, "id": user.user_id, "name": user.name,
           "dept": user.dept, "is_admin": user.is_admin}
    if service:
        svc = services.get(service)
        out["service"] = service
        out["allowed"] = bool(svc) and access.can_use(user, svc, user.ip)
        out["manage"] = bool(svc) and access.can_manage(user, svc)
    return out


@app.get("/api/authz")
def authz(response: Response, service: str | None = None,
          user: User = Depends(current_user)):
    """nginx 가 각 앱 요청 앞에서 부르는 자리 (auth_request).

    통과하면 204 를 주고, 사용자 정보를 **응답 헤더**로 돌려준다.
    nginx 가 그 헤더를 받아 뒤쪽 앱에 그대로 붙여 준다.

        직원 브라우저 → nginx ─(1) /api/authz?service=assets → 포털
                            ←   204 + X-User-Id / Name / Dept / Role
                            ─(2) 그 헤더를 붙여서 → assets 앱

    이렇게 하면 각 앱은 **헤더만 읽으면 된다.** 포털에 물어보는 코드도,
    쿠키를 다루는 코드도 필요 없다. 앱이 스무 개가 되어도 인증 코드는
    포털 한 곳에만 있다.

    한글은 HTTP 헤더에 그대로 담을 수 없어 퍼센트 인코딩해서 보낸다.
    앱에서는 urllib.parse.unquote() 로 되돌린다.

    Role 은 앱이 이해하기 쉬운 두 값으로 줄여서 준다.
        admin  포털 관리자이거나 이 서비스의 담당자 → 삭제 같은 것을 맡는다
        user   그 외 (조회·등록·수정)
    """
    if service:
        svc = services.get(service)
        if not svc or not access.can_use(user, svc, user.ip):
            raise HTTPException(status_code=403, detail="이 서비스를 이용할 권한이 없습니다.")
        role = "admin" if access.can_manage(user, svc) else "user"
    else:
        role = "admin" if user.is_admin else "user"

    response.status_code = 204
    response.headers["X-User-Id"] = user.user_id
    response.headers["X-User-Name"] = quote(user.name or "")
    response.headers["X-User-Dept"] = quote(user.dept or "")
    response.headers["X-User-Role"] = role
    return response


class AuditIn(BaseModel):
    service: str = ""
    action: str
    user: str = ""
    dept: str = ""
    detail: str = ""


@app.post("/api/audit")
def receive_audit(req: AuditIn,
                  x_audit_token: str = Header(default=""),
                  x_service_token: str = Header(default="")):
    """옆 서비스가 자기 동작을 포털 이력에 남긴다.

    ai-report 의 파일 업로드·삭제가 여기로 들어온다.
    서비스별로 이력이 흩어져 있으면 사고가 났을 때 여러 화면을 뒤져야 한다.

    사용자 쿠키가 아니라 **서비스 사이의 공유 토큰**으로 확인한다.
    이건 사람이 아니라 서버가 부르는 자리다.

    헤더 이름을 두 개 받는다.
      X-Service-Token   표준 규칙 v2 가 개발자에게 알려주는 이름 (/api/services/register 와 동일)
      X-Audit-Token     이 endpoint 가 원래 쓰던 이름 (ai-report 가 이걸로 보낸다)
    한쪽만 받으면, 규칙대로 만든 앱의 이력이 403 으로 조용히 사라진다.
    앱은 "실패해도 무시하고 진행"하도록 되어 있어서 아무도 눈치채지 못한다.
    """
    expected = os.environ.get("AUDIT_TOKEN", "")
    if not expected:
        # 토큰을 정하지 않았으면 받지 않는다.
        # 열어두면 사내망 안에서 누구나 이력을 지어낼 수 있다.
        raise HTTPException(status_code=503, detail="AUDIT_TOKEN 이 설정되지 않았습니다.")
    got = x_service_token or x_audit_token
    if not secrets.compare_digest(got, expected):
        raise HTTPException(status_code=403, detail="서비스 토큰이 올바르지 않습니다.")

    memory.log_action(req.user or "?", req.action, req.detail,
                      service=req.service or "")
    return {"ok": True}


class NewUser(BaseModel):
    user_id: str
    name: str
    password: str
    dept: str = ""
    is_admin: bool = False


class ProfileUpdate(BaseModel):
    name: str | None = None
    dept: str | None = None
    is_admin: bool | None = None


class PasswordUpdate(BaseModel):
    password: str


class ActiveUpdate(BaseModel):
    active: bool


class ServiceIn(BaseModel):
    id: str | None = None
    name: str
    description: str = ""
    keywords: str = ""
    url: str = ""
    color: str = "#1f4e79"
    enabled: bool = True


class AccessIn(BaseModel):
    access: str = "all"
    allowed_depts: list[str] = []
    allowed_users: list[str] = []
    excluded_users: list[str] = []
    allowed_ips: list[str] = []
    managers: list[str] = []


@app.get("/admin")
def admin_page():
    return FileResponse("static/admin.html")


# ── 서비스 관리 ──────────────────────────────────────────────
@app.get("/api/admin/services")
def admin_services(_: User = Depends(admin_user)):
    items = services.all_services()
    for s in items:
        s["access_desc"] = access.describe(s)
        s["manager_desc"] = access.describe_managers(s)
    return {
        "services": items,
        "departments": depts.all_depts(),
        # is_admin 을 함께 준다. 접근 범위 화면에서 "이 사람은 관리자라
        # 체크를 풀어도 계속 보입니다" 를 표시하기 위해서다.
        # 그게 없으면 "제외했는데 왜 보이지" 로 한참 헤맨다.
        "users": [
            {"user_id": u["user_id"], "name": u["name"], "dept": u["dept"],
             "is_admin": bool(u["is_admin"])}
            for u in users.all_users() if u["active"]
        ],
    }


class ServiceRegister(BaseModel):
    id: str
    name: str
    description: str = ""
    keywords: str = ""
    url: str = ""
    color: str = "#1f4e79"


@app.post("/api/services/register")
def service_register(req: ServiceRegister, x_service_token: str = Header(default="")):
    """앱이 뜰 때 자기를 등록한다.

    왜 자동 등록이 필요한가 — 앱을 만든 사람은 그 앱의 이름·설명·검색 키워드를
    가장 잘 안다. 그걸 IT 담당자가 관리자 화면에서 옮겨 적게 하면
    앱이 늘 때마다 같은 일을 반복하게 되고, 앱을 고쳐도 포털 설명은 옛날 그대로 남는다.

    **다만 등록과 공개는 다르다.**
    처음 등록되는 서비스는 항상 이렇게 들어온다.

        enabled = False        중지 상태
        access  = restricted   허용 부서·개인 없음 → 아무에게도 안 보인다

    즉 앱이 스스로 켤 수는 없다. 관리자가 접근 범위를 정하고 켜야 직원에게 보인다.
    검토하고 배포하는 흐름을 그대로 지킨다.

    이미 있는 서비스면 **설명 항목만** 갱신한다. 접근 범위·담당자·사용 여부는
    건드리지 않는다. 앱을 재배포했다고 관리자가 정한 권한이 되돌아가면 사고다.
    """
    expected = os.environ.get("AUDIT_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="AUDIT_TOKEN 이 설정되지 않았습니다.")
    if not secrets.compare_digest(x_service_token, expected):
        raise HTTPException(status_code=403, detail="서비스 토큰이 올바르지 않습니다.")

    sid = req.id.strip()
    if not sid or not req.name.strip():
        raise HTTPException(status_code=400, detail="id 와 name 은 필수입니다.")

    fields = dict(description=req.description, keywords=req.keywords,
                  url=req.url, color=req.color)
    if services.get(sid):
        services.update(sid, name=req.name.strip(), **fields)
        return {"registered": False, "updated": True}

    services.create(sid, req.name.strip(), enabled=False, access="restricted", **fields)
    memory.log_action("(자동)", "서비스 자동 등록",
                      f"{req.name} ({sid}) — 접근 범위를 지정하고 켜야 직원에게 보입니다",
                      service=req.name.strip())
    logging.info("서비스 자동 등록 | %s", sid)
    return {"registered": True, "updated": False}


@app.post("/api/admin/services/examples")
def service_examples(me: User = Depends(admin_user)):
    """예시 서비스 넣기. 처음 화면이 비어 있을 때 형태를 보려는 용도."""
    n = services.seed_examples()
    if n:
        memory.log_action(me.user_id, "예시 서비스 등록", f"{n}개")
    return {"added": n}


@app.post("/api/admin/services")
def service_create(req: ServiceIn, me: User = Depends(admin_user)):
    sid = (req.id or "").strip()
    if not sid or not req.name.strip():
        raise HTTPException(status_code=400, detail="ID와 이름을 입력하세요.")
    if services.get(sid):
        raise HTTPException(status_code=400, detail="이미 있는 서비스 ID 입니다.")

    services.create(sid, req.name.strip(), description=req.description,
                    keywords=req.keywords, url=req.url, color=req.color,
                    enabled=req.enabled)
    memory.log_action(me.user_id, "서비스 등록", f"{req.name} ({sid})")
    return {"ok": True}


@app.patch("/api/admin/services/{sid}")
def service_update(sid: str, req: ServiceIn, me: User = Depends(admin_user)):
    if not services.get(sid):
        raise HTTPException(status_code=404, detail="없는 서비스입니다.")
    services.update(sid, name=req.name.strip(), description=req.description,
                    keywords=req.keywords, url=req.url, color=req.color,
                    enabled=req.enabled)
    memory.log_action(me.user_id, "서비스 수정", f"{req.name} ({sid})")
    return {"ok": True}


@app.patch("/api/admin/services/{sid}/access")
def service_access(sid: str, req: AccessIn, me: User = Depends(admin_user)):
    if not services.get(sid):
        raise HTTPException(status_code=404, detail="없는 서비스입니다.")
    if req.access not in ("all", "restricted"):
        raise HTTPException(status_code=400, detail="접근 방식이 올바르지 않습니다.")

    services.update(sid, access=req.access, allowed_depts=req.allowed_depts,
                    allowed_users=req.allowed_users,
                    excluded_users=req.excluded_users, allowed_ips=req.allowed_ips,
                    managers=req.managers)
    memory.log_action(me.user_id, "접근 범위 변경",
                      f"{sid} → {access.describe(services.get(sid))}")
    return {"ok": True}


@app.patch("/api/admin/services/{sid}/enabled")
def service_enabled(sid: str, req: ActiveUpdate, me: User = Depends(admin_user)):
    if not services.get(sid):
        raise HTTPException(status_code=404, detail="없는 서비스입니다.")
    services.update(sid, enabled=req.active)
    memory.log_action(me.user_id, "서비스 사용 토글",
                      f"{sid} → {'사용' if req.active else '중지'}")
    return {"ok": True}


@app.patch("/api/admin/services/{sid}/move")
def service_move(sid: str, direction: int, me: User = Depends(admin_user)):
    services.move(sid, direction)
    return {"ok": True}


@app.delete("/api/admin/services/{sid}")
def service_delete(sid: str, me: User = Depends(admin_user)):
    if not services.delete(sid):
        raise HTTPException(status_code=404, detail="없는 서비스입니다.")
    memory.log_action(me.user_id, "서비스 삭제", sid)
    return {"ok": True}


# ── 부서 관리 ────────────────────────────────────────────────
class DeptIn(BaseModel):
    name: str


@app.get("/api/admin/departments")
def dept_list(_: User = Depends(admin_user)):
    """부서 목록 + 각 부서를 쓰고 있는 곳."""
    return {
        "departments": [
            {"name": d, **depts.usage(d)} for d in depts.all_depts()
        ]
    }


@app.post("/api/admin/departments")
def dept_create(req: DeptIn, me: User = Depends(admin_user)):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="부서명을 입력하세요.")
    if not depts.create(name):
        raise HTTPException(status_code=400, detail="이미 있는 부서입니다.")
    memory.log_action(me.user_id, "부서 추가", name)
    return {"ok": True}


@app.patch("/api/admin/departments/{name}")
def dept_rename(name: str, req: DeptIn, me: User = Depends(admin_user)):
    """부서명 변경.

    계정과 서비스 접근 범위에 적힌 부서명까지 함께 바꾼다.
    한쪽만 바뀌면 그 순간 권한이 조용히 사라진다.
    """
    new = req.name.strip()
    if not new:
        raise HTTPException(status_code=400, detail="부서명을 입력하세요.")
    if not depts.rename(name, new):
        raise HTTPException(status_code=400, detail="변경할 수 없습니다. 같은 이름이 이미 있는지 확인하세요.")
    memory.log_action(me.user_id, "부서명 변경", f"{name} → {new}")
    return {"ok": True}


@app.patch("/api/admin/departments/{name}/move")
def dept_move(name: str, direction: int, _: User = Depends(admin_user)):
    depts.move(name, direction)
    return {"ok": True}


@app.delete("/api/admin/departments/{name}")
def dept_delete(name: str, me: User = Depends(admin_user)):
    u = depts.usage(name)
    if u["users"] or u["services"]:
        used = []
        if u["users"]:
            used.append(f"소속 직원 {len(u['users'])}명")
        if u["services"]:
            used.append(f"서비스 {len(u['services'])}개")
        raise HTTPException(
            status_code=400,
            detail=f"{' · '.join(used)} 이 이 부서를 쓰고 있어 삭제할 수 없습니다.")
    if not depts.delete(name):
        raise HTTPException(status_code=404, detail="없는 부서입니다.")
    memory.log_action(me.user_id, "부서 삭제", name)
    return {"ok": True}


# ── 사용자 관리 ──────────────────────────────────────────────
@app.get("/api/admin/suggest-password")
def suggest_pw(_: User = Depends(admin_user)):
    return {"password": users.suggest_password()}


@app.get("/api/admin/users")
def admin_users(_: User = Depends(admin_user)):
    return {"users": users.all_users(), "departments": depts.all_depts()}


@app.post("/api/admin/users")
def admin_create(req: NewUser, me: User = Depends(admin_user)):
    uid = req.user_id.strip()
    if not uid or not req.name.strip():
        raise HTTPException(status_code=400, detail="아이디와 이름을 입력하세요.")
    err = users.check_password(req.password)
    if err:
        raise HTTPException(status_code=400, detail=err)
    if users.get(uid):
        raise HTTPException(status_code=400, detail="이미 있는 아이디입니다.")

    dept = req.dept.strip()
    # 화면에서 목록으로만 고르게 해두었지만, API 를 직접 부르면 뚫린다.
    # 오타 하나가 "권한을 줬는데 안 보인다"로 이어지므로 여기서도 막는다.
    if dept and not depts.exists(dept):
        raise HTTPException(status_code=400,
                            detail=f"등록되지 않은 부서입니다: {dept}")

    users.create(uid, req.name.strip(), req.password,
                 dept=dept, is_admin=req.is_admin)
    memory.log_action(me.user_id, "사용자 추가",
                      f"{req.name} ({uid}) / {dept or '부서 없음'}")
    return {"ok": True}


# ── 계정 일괄 등록 ──────────────────────────────────────────
# 직원이 500명이면 화면에서 하나씩 만들 수 없다. 인사 담당자가 들고 있는
# 엑셀 명부를 그대로 받는다. 검사와 적용을 나눈 이유는 app/bulk_users.py 참고.

@app.get("/api/admin/users/template")
def users_template(_: User = Depends(admin_user)):
    from fastapi.responses import Response as RawResponse
    return RawResponse(
        content=bulk_users.template_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 'attachment; filename="portal_users_template.csv"'},
    )


@app.post("/api/admin/users/check")
async def users_check(file: UploadFile = File(...),
                      create_depts: bool = Form(False),
                      _: User = Depends(admin_user)):
    """올린 명부를 **읽기만** 한다. 계정도 부서도 만들지 않는다."""
    blob = await file.read()
    if len(blob) > 4 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="파일이 너무 큽니다. 4MB 까지 올릴 수 있습니다.")
    try:
        return bulk_users.check(file.filename or "", blob, create_depts=create_depts)
    except bulk_users.BulkError as e:
        raise HTTPException(status_code=400, detail=str(e))


class BulkApply(BaseModel):
    rows: list[dict] = []
    # 명부에 있는데 포털에 없는 부서를 함께 만들지. 화면에서 켜야 참이 된다.
    create_depts: bool = False


@app.post("/api/admin/users/bulk")
def users_bulk(req: BulkApply, me: User = Depends(admin_user)):
    """검사에서 통과한 줄만 실제로 만든다."""
    if not req.rows:
        raise HTTPException(status_code=400, detail="만들 계정이 없습니다.")
    if len(req.rows) > 2000:
        raise HTTPException(status_code=400, detail="한 번에 2000명까지 만들 수 있습니다.")
    r = bulk_users.apply(req.rows, create_depts=req.create_depts)
    # 부서를 만든 것은 따로 남긴다. 계정 등록에 묻히면 나중에
    # "이 부서 누가 만들었지" 를 못 찾는다.
    if r.get("made_depts"):
        memory.log_action(me.user_id, "부서 추가",
                          "명부에서 함께 만듦: " + ", ".join(r["made_depts"]))
    if r["made"]:
        memory.log_action(me.user_id, "계정 일괄 등록",
                          f"{len(r['made'])}명 추가"
                          + (f" · {len(r['failed'])}명 실패" if r["failed"] else ""))
    return r


@app.patch("/api/admin/users/{user_id}")
def admin_profile(user_id: str, req: ProfileUpdate, me: User = Depends(admin_user)):
    if not users.get(user_id):
        raise HTTPException(status_code=404, detail="없는 계정입니다.")
    if req.is_admin is False and users.admin_count(exclude=user_id) == 0:
        raise HTTPException(status_code=400,
                            detail="마지막 관리자입니다. 다른 계정을 먼저 관리자로 지정하세요.")
    if req.dept and not depts.exists(req.dept.strip()):
        raise HTTPException(status_code=400,
                            detail=f"등록되지 않은 부서입니다: {req.dept}")

    users.update_profile(user_id, req.name,
                         None if req.dept is None else req.dept.strip(),
                         req.is_admin)
    memory.log_action(me.user_id, "사용자 수정", user_id)
    return {"ok": True}


@app.patch("/api/admin/users/{user_id}/password")
def admin_password(user_id: str, req: PasswordUpdate, me: User = Depends(admin_user)):
    if not users.get(user_id):
        raise HTTPException(status_code=404, detail="없는 계정입니다.")
    err = users.check_password(req.password)
    if err:
        raise HTTPException(status_code=400, detail=err)

    users.set_password(user_id, req.password, must_change=True)
    memory.log_action(me.user_id, "비밀번호 초기화", user_id)
    return {"ok": True}


@app.get("/api/admin/users/{user_id}/footprint")
def admin_footprint(user_id: str, _: User = Depends(admin_user)):
    """지우기 전에 "무엇이 딸려 있는지" 보여준다.

    확인 창에 숫자가 없으면 사람은 그냥 누른다. 숫자가 보여야 손이 멈춘다.
    """
    if not users.get(user_id):
        raise HTTPException(status_code=404, detail="없는 계정입니다.")
    return {
        "chats": memory.count_user_sessions(user_id),
        "files": uploads.count_user_files(user_id),
        "services": services.services_of_user(user_id),
    }


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: str, purge: bool = False,
                      me: User = Depends(admin_user)):
    """계정을 지운다. 되돌릴 수 없다.

    purge=false  계정만 지운다. 대화·올린 파일은 남는다. (기본)
    purge=true   그 사람의 대화·파일·기억까지 함께 지운다.

    어느 쪽이든 **접근 범위와 담당자 명단에서는 반드시 걷어낸다.**
    거기 남아 있으면 나중에 같은 아이디로 만든 계정이 앞사람 권한을
    그대로 물려받는다. 그건 취향 문제가 아니라 사고다.
    """
    if not users.get(user_id):
        raise HTTPException(status_code=404, detail="없는 계정입니다.")
    if user_id == me.user_id:
        raise HTTPException(status_code=400,
                            detail="자기 계정은 지울 수 없습니다. 다른 관리자에게 부탁하세요.")
    if users.admin_count(exclude=user_id) == 0:
        raise HTTPException(status_code=400,
                            detail="마지막 관리자입니다. 다른 계정을 먼저 관리자로 지정하세요.")

    touched = services.purge_user(user_id)
    removed = {}
    if purge:
        removed = memory.purge_user(user_id)
        removed["파일"] = uploads.purge_user(user_id)
    users.delete(user_id)

    memory.log_action(me.user_id, "계정 삭제",
                      user_id + (" · 기록까지 함께" if purge else " · 계정만")
                      + (" · 접근 범위 정리: " + ", ".join(touched) if touched else ""))
    return {"ok": True, "services": touched, "removed": removed}


@app.patch("/api/admin/users/{user_id}/active")
def admin_active(user_id: str, req: ActiveUpdate, me: User = Depends(admin_user)):
    if not users.get(user_id):
        raise HTTPException(status_code=404, detail="없는 계정입니다.")
    if not req.active:
        if user_id == me.user_id:
            raise HTTPException(status_code=400, detail="자기 계정은 중지할 수 없습니다.")
        if users.admin_count(exclude=user_id) == 0:
            raise HTTPException(status_code=400, detail="마지막 관리자는 중지할 수 없습니다.")

    users.set_active(user_id, req.active)
    memory.log_action(me.user_id, "계정 상태 변경",
                      f"{user_id} → {'사용' if req.active else '중지'}")
    return {"ok": True}


# ── 이력 ─────────────────────────────────────────────────────
@app.get("/api/admin/audit")
def admin_audit(_: User = Depends(admin_user), limit: int = 200):
    """관리 이력과 사용 기록을 **나눠서** 돌려준다.

    합쳐서 내려주면 화면에서 한 표로 그리게 되고, 그러면
    직원이 무엇을 물었는지가 관리자 눈에 그대로 들어온다.
    사용 기록에는 질문 내용이 들어가지 않는다.
    """
    # 도구가 어느 앱의 것인지. 채팅 이력을 서비스별로 거르는 데 쓴다.
    # 기록에는 도구 이름만 남으므로 화면 혼자서는 알 수 없다.
    names = {s["id"]: s["name"] for s in services.all_services()}
    tool_svc = {t: (names.get(sid) or sid or "포털")
                for t, sid in registry.tool_services().items()}

    # 서비스 목록에서 '포털' 은 빼고 준다. 화면이 맨 앞에 따로 넣기 때문에
    # 여기에도 들어 있으면 드롭다운에 '포털' 이 두 번 나온다.
    svc_list = [s for s in memory.audit_services() if s != "포털"]

    return {
        "audit": memory.audit_logs(limit),
        "usage": memory.usage_logs(limit),
        "services": svc_list,
        "actions": memory.audit_actions(),
        "tool_services": tool_svc,
        "policy": {
            "text_logging": memory.LOG_TEXT,
            "log_days": memory.LOG_DAYS,
        },
    }


@app.get("/api/sessions")
def sessions(user: User = Depends(current_user)):
    """이 사용자의 대화 목록."""
    return {"sessions": memory.list_sessions(user.user_id)}


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str, user: User = Depends(current_user)):
    """대화 전문. 본인 것만 조회된다."""
    return {"turns": memory.load_session(session_id, user.user_id)}


@app.delete("/api/sessions/{session_id}")
def session_delete(session_id: str, user: User = Depends(current_user)):
    return {"deleted": memory.delete_session(session_id, user.user_id)}


class MyPassword(BaseModel):
    current: str
    new: str


@app.get("/password")
def password_page():
    return FileResponse("static/password.html")


@app.post("/api/me/password")
def change_my_password(req: MyPassword, me: User = Depends(current_user)):
    """본인 비밀번호 변경. 현재 비밀번호를 반드시 확인한다."""
    if not users.authenticate(me.user_id, req.current):
        raise HTTPException(status_code=400, detail="현재 비밀번호가 올바르지 않습니다.")

    err = users.check_password(req.new)
    if err:
        raise HTTPException(status_code=400, detail=err)
    if req.current == req.new:
        raise HTTPException(status_code=400, detail="이전과 다른 비밀번호를 사용하세요.")

    users.set_password(me.user_id, req.new, must_change=False)
    logging.info("비밀번호 변경(본인) | user=%s", me.user_id)

    # 변경 후 새 토큰을 발급해 must_change 표시를 없앤다
    u = users.get(me.user_id)
    token, expires_in = auth.issue_token(u)
    return {"ok": True, "token": token, "expires_in": expires_in}


@app.get("/api/memory")
def my_memory(user: User = Depends(current_user)):
    """저장된 기억 확인용."""
    return {"notes": memory.list_notes(user.user_id)}


@app.delete("/api/memory/{note_id}")
def forget(note_id: int, user: User = Depends(current_user)):
    return {"deleted": memory.delete_note(user.user_id, note_id)}


@app.get("/api/logs")
def logs(_: User = Depends(admin_user)):
    """사용 기록. 내용은 포함되지 않는다."""
    return {"logs": memory.usage_logs()}



# ── 챗에 파일 붙이기 ─────────────────────────────────────────
@app.post("/api/upload")
async def upload(file: UploadFile = File(...),
                 session_id: str = Form(default=""),
                 user: User = Depends(current_user)):
    """챗 입력창에 붙인 파일을 받는다.

    포털은 파일을 **열어보지 않는다.** 어떤 앱에 넘길지는 모델이 정하고,
    실제 분석은 그 앱이 한다.

    이력 기록에 파일 이름은 남기지 않는다. 이름만으로도
    "이력서_홍길동.pdf" 처럼 개인정보가 드러날 수 있다.
    """
    blob = await file.read()
    try:
        info = uploads.save(user.user_id, session_id, file.filename or "", blob)
    except uploads.UploadError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 같은 파일을 다시 올린 것이면 이력을 또 남기지 않는다.
    # 끌어다 놓기를 두 번 했다는 이유로 기록이 두 줄이 되면 안 된다.
    if not info.get("duplicate"):
        memory.log_action(user.user_id, "챗 파일 첨부",
                          f"{info['ext']} · {info['size'] // 1024}KB", service="포털")
    return info


@app.get("/api/upload/{file_id}")
def upload_get(file_id: str, user: User = Depends(current_user)):
    """올린 파일 내려받기.

    **올린 본인과 UPLOAD_VIEWERS 에 적힌 계정만** 열 수 있다.
    관리자라는 이유만으로는 열리지 않는다 (app/uploads.py 참고).
    """
    got = uploads.read(file_id, user.user_id)
    if not got:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    meta, blob = got
    if meta["user_id"] != user.user_id:
        # 남의 파일을 열어본 것은 반드시 기록에 남긴다
        memory.log_action(user.user_id, "타인 첨부파일 열람",
                          f"{meta['user_id']} 님의 {meta['ext']} 파일", service="포털")
    from fastapi.responses import Response as RawResponse
    from urllib.parse import quote as _q
    return RawResponse(
        content=blob,
        media_type="application/octet-stream",
        headers={"Content-Disposition":
                 f"attachment; filename*=UTF-8\'\'{_q(meta['name'])}",
                 "Cache-Control": "no-store"},
    )


@app.get("/api/admin/uploads")
def admin_uploads(user: User = Depends(current_user)):
    """올라온 파일 목록. **UPLOAD_VIEWERS 계정만** 볼 수 있다.

    admin_user 를 쓰지 않는 이유 — 관리자 권한과 파일 열람은 다른 문제다.
    관리자를 한 명 더 만들었다는 이유로 이력서까지 열리면 안 된다.
    """
    if user.user_id not in uploads.VIEWERS:
        raise HTTPException(status_code=403, detail="첨부파일을 열람할 권한이 없습니다.")
    rows = uploads.recent()
    for r in rows:
        u = users.get(r["user_id"]) or {}
        r["user_name"] = u.get("name", r["user_id"])
        r["size_kb"] = r.pop("size") // 1024
    return {"uploads": rows, "keep_days": uploads.KEEP_DAYS}


@app.get("/api/admin/usage")
def admin_usage(days: int = 30, _: User = Depends(admin_user)):
    """AI 공급자에 얼마나 썼는지.

    직원이 무엇을 물었는지가 아니라 **얼마가 나갔는지**를 보는 곳이다.
    특히 그림 읽기는 눈에 안 띄게 커진다 — 엑셀 하나를 열었을 뿐인데
    안에 붙은 캡처 다섯 장이 통째로 넘어간다.
    """
    return usage.report(max(1, min(days, 365)))


@app.post("/api/chat")
def chat(req: ChatRequest, user: User = Depends(current_user)):
    """채팅 1회 처리.

    session_id 를 함께 보내면 이전 대화 맥락이 이어진다.
    """
    return agent.chat(user=user, message=req.message, session_id=req.session_id,
                      file_ids=req.file_ids)


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest, user: User = Depends(current_user)):
    """진행 상황을 단계별로 보내는 채팅 엔드포인트 (SSE)."""
    def gen():
        try:
            for ev in agent.chat_stream(user=user, message=req.message,
                                        session_id=req.session_id,
                                        file_ids=req.file_ids):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001
            logging.exception("스트림 오류")
            err = {"type": "error", "text": "처리 중 오류가 발생했습니다."}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
