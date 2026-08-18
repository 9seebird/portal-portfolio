from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import pandas as pd
import json
import os
import re
import glob
import threading
import time

app = FastAPI()

DATA_DIR = "/data"

# === 업로드 보안 설정 (docker-compose environment 로 조정 가능) ===
# 허용 확장자: 쉼표 구분. 이 서비스는 엑셀 리포트만 읽으므로 기본 .xlsx 만 허용.
ALLOWED_UPLOAD_EXTS = tuple(
    e.strip().lower() if e.strip().startswith(".") else "." + e.strip().lower()
    for e in os.environ.get("ALLOWED_UPLOAD_EXTS", ".xlsx").split(",")
    if e.strip()
)
# 최대 업로드 크기 (MB)
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "10"))

# 이 리포트가 요구하는 필수 컬럼 (내용 검증용)
REQUIRED_COLUMNS = ["date", "name", "usageCount", "inputCharge", "outputCharge"]

# === 포탈 연동 (관리자 확인) ===
# 업로드/삭제는 포탈 관리자만 가능. 브라우저가 보내는 포탈 세션 쿠키(portal_token)를
# 포탈의 /api/me 에 전달해서 관리자 여부를 확인한다.
#  - 로컬: http://demo-portal:8080  (같은 compose 네트워크의 포탈 컨테이너)
#  - 서버: 포탈이 떠 있는 주소로 변경 (예: http://10.20.10.10:8080)
PORTAL_API_URL = os.environ.get("PORTAL_API_URL", "http://demo-portal:8080")

import urllib.request

def get_portal_user(request: Request) -> dict:
    """포탈 세션 쿠키로 포탈에 사용자 정보를 물어본다. 실패하면 빈 dict."""
    token = request.cookies.get("portal_token", "")
    if not token:
        return {}
    try:
        req = urllib.request.Request(
            PORTAL_API_URL.rstrip("/") + "/api/me",
            headers={"Cookie": f"portal_token={token}"},
        )
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return {}   # 포탈에 못 물어보면 관리자 아님으로 처리 (안전한 쪽으로)

def require_admin(request: Request):
    """관리자가 아니면 403. 업로드/삭제 앞에서 호출."""
    me = get_portal_user(request)
    if not me.get("is_admin"):
        raise HTTPException(
            status_code=403,
            detail="관리자만 사용할 수 있는 기능입니다. 포탈에 관리자 계정으로 로그인한 뒤 이용해주세요.",
        )

# === 서비스 접근 권한 ===
# 포탈이 이 서비스를 목록에서 숨겨 주긴 하지만, 그건 화면상의 편의일 뿐이다.
# 주소를 직접 치면 그대로 열린다. 실제 차단은 여기서 해야 한다.
#
# 누가 쓸 수 있는지는 포탈 관리자 화면에서 정한다. 이 앱은 판정하지 않고
# 물어보기만 한다. 서비스마다 명단을 따로 두면 관리자 화면에서 범위를
# 바꿔도 이쪽은 그대로여서 "포탈엔 없는데 주소로는 들어가진다"가 생긴다.
SERVICE_ID = os.environ.get("SERVICE_ID", "ai-report")

def check_access(request: Request) -> dict:
    """포탈에 '이 사람이 이 서비스를 써도 되나'를 물어본다."""
    token = request.cookies.get("portal_token", "")
    if not token:
        return {}
    try:
        req = urllib.request.Request(
            PORTAL_API_URL.rstrip("/") + "/api/verify?service=" + SERVICE_ID,
            headers={"Cookie": f"portal_token={token}"},
        )
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return {}   # 포탈에 못 물어보면 거부 (안전한 쪽으로)

def is_trusted_service(request: Request) -> bool:
    """포탈이 서버에서 직접 부르는 경우.

    챗이 "이번 달 AI 비용 얼마야"에 답하려면 포탈 서버가 이 API 를 불러야 하는데,
    그건 브라우저가 아니라서 쿠키가 없다. 대신 공유 토큰으로 확인한다.

    포탈은 **이미 사용자 권한을 확인한 뒤에만** 이 도구를 노출하므로,
    포탈이 물어봤다는 것 자체가 그 사용자가 권한이 있다는 뜻이다.
    (권한이 없으면 도구가 목록에 아예 없다)
    """
    tok = request.headers.get("x-service-token", "")
    return bool(AUDIT_TOKEN) and tok == AUDIT_TOKEN


def require_manage(request: Request) -> dict:
    """이 서비스의 담당자만. 파일 삭제처럼 되돌릴 수 없는 동작 앞에서 호출.

    "쓸 수 있다"와 "관리할 수 있다"는 다른 문제다.
    부서 전체가 리포트를 보고 파일을 올릴 수 있어도,
    남이 올린 파일을 지우는 건 담당자만 할 수 있어야 한다.

    누가 담당자인지는 포탈 관리자 화면에서 정한다. 이 앱은 판정하지 않는다.
    """
    me = check_access(request)
    if not me.get("logged_in"):
        raise HTTPException(status_code=401, detail="포탈에 로그인한 뒤 이용해주세요.")
    if not me.get("manage"):
        raise HTTPException(
            status_code=403,
            detail="이 서비스의 담당자만 삭제할 수 있습니다. "
                   "포탈 관리자에게 담당자 지정을 요청해주세요.",
        )
    return me


def require_access(request: Request) -> dict:
    """로그인 + 이 서비스 사용 권한. 화면과 데이터 조회 앞에서 호출."""
    if is_trusted_service(request):
        # 포탈이 서버에서 부른 것이다. 누구를 대신해 부른 것인지는
        # 헤더에 실려 온다. 그대로 기록에 남겨야 "누가 올렸나"가 남는다.
        # (없으면 예전처럼 'portal' 로 남는다 — 옛 포탈과도 그냥 돈다)
        from urllib.parse import unquote
        return {"logged_in": True, "allowed": True,
                "id": request.headers.get("x-user-id") or "portal",
                "name": unquote(request.headers.get("x-user-name", "")),
                "dept": unquote(request.headers.get("x-user-dept", "")),
                "via": "챗"}
    me = check_access(request)
    if not me.get("logged_in"):
        raise HTTPException(status_code=401, detail="포탈에 로그인한 뒤 이용해주세요.")
    if not me.get("allowed"):
        raise HTTPException(
            status_code=403,
            detail="이 서비스를 이용할 권한이 없습니다. IT 담당자에게 문의해주세요.",
        )
    return me

@app.get("/api/whoami")
def api_whoami(request: Request):
    """프론트에서 업로드/관리 버튼 노출 여부 판단용."""
    me = get_portal_user(request)
    return {"success": True,
            "data": {"logged_in": bool(me.get("logged_in")), "is_admin": bool(me.get("is_admin"))},
            "error": None}

# === 업로드/삭제 기록 (관리자가 확인) ===
from datetime import datetime, timezone, timedelta

# 한국 시간 (컨테이너는 UTC로 돌기 때문에 표기용으로 +9 고정)
KST = timezone(timedelta(hours=9))

LOG_PATH = os.path.join(DATA_DIR, "upload_log.json")

# 포탈 중앙 이력으로 보낼 때 쓰는 값들
SERVICE_NAME = os.environ.get("SERVICE_NAME", "AI 리포트")
AUDIT_TOKEN = os.environ.get("AUDIT_TOKEN", "")

# === 포탈에 자기를 등록 ===
#
# 앱을 만든 사람이 이 앱의 이름·설명·검색 키워드를 가장 잘 안다.
# 그걸 IT 담당자가 관리자 화면에 옮겨 적게 하면, 앱이 늘 때마다 같은 일을
# 반복하게 되고 앱을 고쳐도 포탈 쪽 설명은 옛날 그대로 남는다.
#
# 등록한다고 바로 공개되지는 않는다. 처음 등록되면 포탈은 이걸
# "중지 + 접근 범위 없음" 으로 만들어 두고, 관리자가 범위를 정하고 켜야
# 직원에게 보인다. 검토하고 배포하는 흐름은 그대로다.
SERVICE_META = {
    "id": SERVICE_ID,
    "name": SERVICE_NAME,
    "description": "사용자별 AI 도구 사용 현황과 월별 요금을 확인합니다",
    # 직원이 실제로 쓸 표현을 넣는다. 챗의 앱 검색이 이 값을 쓴다.
    "keywords": "AI, 사용량, 비용, 요금, 사용료, 리포트, 토큰, 호출, 웍스AI",
    "url": "/" + SERVICE_ID + "/",
    "color": "#1f4e79",
}

# 몇 번까지 다시 해볼지. 배포하면 앱들이 한꺼번에 뜨는데, 포탈이 아직
# 안 떠 있으면 첫 시도는 거의 반드시 실패한다("Name or service not known").
# 그 한 번으로 포기하면 **관리자 화면에 이 앱만 안 뜬다.** 화면에는
# 아무 단서도 없어서 원인 찾는 데 한참 걸린다. 그래서 몇 번 더 두드린다.
REGISTER_TRIES = int(os.environ.get("REGISTER_TRIES", "10"))
REGISTER_WAIT = float(os.environ.get("REGISTER_WAIT", "3"))


def _register_once() -> bool:
    req = urllib.request.Request(
        PORTAL_API_URL.rstrip("/") + "/api/services/register",
        data=json.dumps(SERVICE_META).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "X-Service-Token": AUDIT_TOKEN},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        out = json.loads(r.read().decode("utf-8"))
    print(f"[portal] 서비스 등록 — {out}", flush=True)
    return True


def _register_loop() -> None:
    """포탈이 뜰 때까지 몇 번 더 두드린다. 실패해도 앱은 정상 동작한다."""
    for i in range(1, REGISTER_TRIES + 1):
        try:
            _register_once()
            return
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            if i < REGISTER_TRIES:
                time.sleep(REGISTER_WAIT)
    print(f"[portal] 서비스 등록 실패 — {REGISTER_TRIES}번 시도했습니다. "
          f"({last}) 앱은 계속 동작합니다. "
          f"AUDIT_TOKEN 이 포털과 같은지, 포털이 떠 있는지 확인하세요.", flush=True)


@app.on_event("startup")
def register_with_portal():
    """뜰 때 포탈에 알린다.

    별도 스레드에서 돈다. 여기서 기다리면 그만큼 앱이 늦게 뜨고,
    포탈이 영영 안 뜨면 이 앱도 못 뜬다.
    """
    if not AUDIT_TOKEN:
        print("[portal] AUDIT_TOKEN 이 없어 등록을 건너뜁니다.", flush=True)
        return
    threading.Thread(target=_register_loop, daemon=True).start()


def push_audit(action: str, me: dict, detail: str):
    """포탈 중앙 이력(/api/audit)으로 전송. 실패해도 무시 (로컬 기록은 남음)."""
    try:
        payload = json.dumps({
            "service": SERVICE_NAME,
            "action": action,
            "user": str(me.get("id", "") or "?"),
            "dept": str(me.get("dept", "") or ""),
            "detail": detail,
        }).encode("utf-8")
        req = urllib.request.Request(
            PORTAL_API_URL.rstrip("/") + "/api/audit",
            data=payload,
            headers={"Content-Type": "application/json", "X-Audit-Token": AUDIT_TOKEN},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass

# 조회 기록 묶기 — {(사용자, 파일): 마지막 기록 시각}
# 컨테이너를 다시 띄우면 비워진다. 이력이 조금 더 남는 정도라 문제되지 않는다.
_VIEW_SEEN: dict = {}
VIEW_QUIET_MIN = int(os.environ.get("VIEW_QUIET_MIN", "10"))

def log_view(me: dict, filename: str):
    """리포트 조회 기록. 같은 사람이 같은 파일을 계속 봐도 한 번만 남긴다."""
    key = (str(me.get("id") or "?"), filename)
    now = datetime.now(KST)
    last = _VIEW_SEEN.get(key)
    if last and (now - last).total_seconds() < VIEW_QUIET_MIN * 60:
        return
    _VIEW_SEEN[key] = now
    append_log("view", me, filename)
    push_audit("리포트 조회", me, filename)


def append_log(action: str, me: dict, filename: str, size=None, rows=None):
    """업로드/삭제 기록을 남긴다. (최근 1000건 유지)"""
    try:
        logs = []
        if os.path.exists(LOG_PATH):
            with open(LOG_PATH, "r", encoding="utf-8") as f:
                logs = json.load(f)
        logs.append({
            "time": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,                      # "upload" / "delete"
            "user": str(me.get("id", "") or "?"),
            "dept": str(me.get("dept", "") or ""),
            "file": filename,
            "size": size,
            "rows": rows,
        })
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(logs[-1000:], f, ensure_ascii=False, indent=1)
    except Exception:
        pass  # 기록 실패가 업로드 자체를 막지는 않게

@app.get("/api/logs")
def api_logs(request: Request):
    """업로드/삭제/조회 기록 (담당자 전용). 최신순."""
    require_manage(request)
    logs = []
    if os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except Exception:
            logs = []
    return {"success": True, "data": {"logs": list(reversed(logs))}, "error": None}

def safe_data_path(filename: str) -> str:
    """
    파일명을 안전하게 정리해서 DATA_DIR 안의 경로로 만든다.
    - 경로 조작(../ 등) 방지: basename만 사용
    - DATA_DIR 밖을 가리키면 거부
    """
    name = os.path.basename(filename or "").strip()
    if not name or name.startswith("."):
        raise HTTPException(status_code=400, detail="잘못된 파일명입니다.")
    path = os.path.realpath(os.path.join(DATA_DIR, name))
    if not path.startswith(os.path.realpath(DATA_DIR) + os.sep):
        raise HTTPException(status_code=400, detail="잘못된 파일 경로입니다.")
    return path

@app.get("/api/files")
def list_files(request: Request):
    require_access(request)
    """List all Excel files in the data directory"""
    files = sorted(glob.glob(os.path.join(DATA_DIR, "*.xlsx")))
    return [{"name": os.path.basename(f), "path": f} for f in files]

@app.post("/api/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    """
    엑셀 파일 업로드 (포탈에 로그인한 직원 누구나. 누가 올렸는지 기록됨).
    보안 순서: 로그인 확인 → 확장자 화이트리스트 → 크기 제한 → 파일 서명(PK) 확인
              → 실제 엑셀로 열리는지 + 필수 컬럼 검증 → 저장 + 기록
    """
    # 이 서비스를 쓸 수 있는 사람이면 올릴 수 있다.
    # 로그인만 확인하면 권한 없는 사람도 데이터를 밀어 넣을 수 있다.
    # (누가 올렸는지는 기록에 남는다)
    me = require_access(request)
    # 1) 파일명 정리 + 확장자 화이트리스트
    name = os.path.basename(file.filename or "").strip()
    ext = os.path.splitext(name)[1].lower()
    if not name or ext not in ALLOWED_UPLOAD_EXTS:
        allowed = ", ".join(ALLOWED_UPLOAD_EXTS)
        return {"success": False, "data": None,
                "error": f"허용되지 않는 파일 형식입니다. ({allowed} 만 업로드 가능)"}

    # 안전하지 않은 문자는 _ 로 치환 (한글/영문/숫자/._- 만 허용)
    base, _ = os.path.splitext(name)
    base = re.sub(r"[^0-9A-Za-z가-힣._\- ]", "_", base).strip() or "upload"
    name = base + ext

    # 2) 크기 제한
    content = await file.read()
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        return {"success": False, "data": None,
                "error": f"파일이 너무 큽니다. (최대 {MAX_UPLOAD_MB}MB)"}
    if len(content) == 0:
        return {"success": False, "data": None, "error": "빈 파일입니다."}

    # 3) 파일 서명 확인 — xlsx/docx 등 오피스 파일은 ZIP 형식(PK)으로 시작.
    #    확장자만 xlsx로 바꾼 실행파일 등을 여기서 걸러낸다.
    if ext in (".xlsx", ".docx", ".pptx") and not content.startswith(b"PK"):
        return {"success": False, "data": None,
                "error": "정상적인 오피스 파일이 아닙니다. (파일 내용이 확장자와 다름)"}

    # 4) 내용 검증 — 실제 엑셀로 열리고, 리포트가 읽을 수 있는 형식인지
    #    (a) Raw Data  : date/name/usageCount/... 컬럼을 가진 원본 로그  → 권장
    #    (b) 집계 엑셀 : 웍스AI 대시보드 [다운로드] 파일 (KPI요약/분포_* 시트)
    rows = None
    if ext == ".xlsx":
        import io
        try:
            xl = pd.ExcelFile(io.BytesIO(content))
        except Exception:
            return {"success": False, "data": None,
                    "error": "엑셀 파일을 읽을 수 없습니다. 파일이 손상되었거나 형식이 다릅니다."}

        sheets = list(xl.sheet_names)
        is_agg = any(s in sheets for s in ("KPI요약", "분포_사용자별"))
        if is_agg:
            rows = None
        else:
            try:
                df = xl.parse(sheets[0])
            except Exception:
                return {"success": False, "data": None,
                        "error": "엑셀 파일을 읽을 수 없습니다."}
            missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
            if missing:
                return {"success": False, "data": None,
                        "error": f"리포트가 읽을 수 있는 엑셀이 아닙니다. 없는 컬럼: {', '.join(missing)} "
                                 f"(웍스AI Raw Data 엑셀 또는 이용통계 집계 엑셀을 올려주세요)"}
            rows = int(len(df))

    # 5) 저장 (동일 이름이 있으면 덮어씀 = 월 데이터 갱신 용도)
    path = safe_data_path(name)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)

    # 6) 기록: 누가 어떤 파일을 올렸는지 (서비스 내 기록 + 포탈 중앙 이력)
    append_log("upload", me, name, size=len(content), rows=rows)
    push_audit("파일 업로드", me, f"{name}" + (f" ({rows}행)" if rows else ""))

    return {"success": True,
            "data": {"name": name, "size": len(content), "rows": rows},
            "error": None}

@app.delete("/api/files/{filename}")
def delete_file(filename: str, request: Request):
    """업로드된 엑셀 파일 삭제 (이 서비스의 담당자 전용)."""
    me = require_manage(request)
    path = safe_data_path(filename)
    if not os.path.exists(path):
        return {"success": False, "data": None, "error": "파일이 없습니다."}
    os.remove(path)
    append_log("delete", me, os.path.basename(path))
    push_audit("파일 삭제", me, os.path.basename(path))
    return {"success": True, "data": {"deleted": os.path.basename(path)}, "error": None}

@app.get("/api/preview/{filename}")
def get_preview(filename: str, request: Request):
    require_access(request)
    """Quick summary for preview cards"""
    filepath = safe_data_path(filename)   # 경로 조작 방지
    if not os.path.exists(filepath):
        return {"error": "File not found"}
    
    df = pd.read_excel(filepath)
    df['date'] = pd.to_datetime(df['date'])
    
    total_charge = float(df['inputCharge'].sum() + df['outputCharge'].sum())
    total_users = int(df['name'].nunique())
    total_usage = int(df['usageCount'].sum())
    date_min = df['date'].min()
    date_max = df['date'].max()
    
    # Top 3 users by charge
    top_users = df.groupby('name').apply(
        lambda x: x['inputCharge'].sum() + x['outputCharge'].sum()
    ).nlargest(3).reset_index()
    top_users.columns = ['name', 'charge']
    
    return {
        "filename": filename,
        "month": date_min.strftime('%Y년 %m월'),
        "dateRange": f"{date_min.strftime('%m/%d')} ~ {date_max.strftime('%m/%d')}",
        "totalCharge": round(total_charge, 2),
        "totalUsers": total_users,
        "totalUsage": total_usage,
        "topUsers": json.loads(top_users.to_json(orient='records', force_ascii=False)),
    }

@app.get("/api/data/{filename}")
def get_data(filename: str, request: Request):
    require_access(request)
    """Read and process an Excel file"""
    filepath = safe_data_path(filename)   # 경로 조작 방지
    if not os.path.exists(filepath):
        return {"error": "File not found"}
    
    df = pd.read_excel(filepath)
    
    # Parse date
    df['date'] = pd.to_datetime(df['date'])
    
    # Per-user summary
    user_summary = df.groupby(['name', 'departmentCode']).agg(
        totalUsageCount=('usageCount', 'sum'),
        totalInputToken=('inputToken', 'sum'),
        totalOutputToken=('outputToken', 'sum'),
        totalInputCharge=('inputCharge', 'sum'),
        totalOutputCharge=('outputCharge', 'sum'),
        totalCharge=('inputCharge', lambda x: x.sum() + df.loc[x.index, 'outputCharge'].sum()),
        activeDays=('date', 'nunique'),
        modelsUsed=('model', lambda x: list(x.unique())),
        toolsUsed=('toolName', lambda x: list(x.unique())),
    ).reset_index()
    
    # Recalculate totalCharge properly
    user_summary['totalCharge'] = user_summary['totalInputCharge'] + user_summary['totalOutputCharge']
    
    # Sort by total charge descending
    user_summary = user_summary.sort_values('totalCharge', ascending=False)
    
    # Per-user detail (by model)
    user_model = df.groupby(['name', 'model']).agg(
        usageCount=('usageCount', 'sum'),
        inputToken=('inputToken', 'sum'),
        outputToken=('outputToken', 'sum'),
        inputCharge=('inputCharge', 'sum'),
        outputCharge=('outputCharge', 'sum'),
    ).reset_index()
    user_model['totalCharge'] = user_model['inputCharge'] + user_model['outputCharge']
    user_model = user_model.sort_values(['name', 'totalCharge'], ascending=[True, False])
    
    # Per-user detail (by toolName)
    user_tool = df.groupby(['name', 'toolName']).agg(
        usageCount=('usageCount', 'sum'),
        inputCharge=('inputCharge', 'sum'),
        outputCharge=('outputCharge', 'sum'),
    ).reset_index()
    user_tool['totalCharge'] = user_tool['inputCharge'] + user_tool['outputCharge']
    user_tool = user_tool.sort_values(['name', 'totalCharge'], ascending=[True, False])
    
    # Overall stats
    date_range = f"{df['date'].min().strftime('%Y-%m-%d')} ~ {df['date'].max().strftime('%Y-%m-%d')}"
    total_charge = float(df['inputCharge'].sum() + df['outputCharge'].sum())
    total_users = int(df['name'].nunique())
    total_usage = int(df['usageCount'].sum())
    
    # Department summary
    dept_summary = df.groupby('departmentCode').agg(
        totalCharge=('inputCharge', lambda x: x.sum() + df.loc[x.index, 'outputCharge'].sum()),
        userCount=('name', 'nunique'),
        usageCount=('usageCount', 'sum'),
    ).reset_index()
    dept_summary['totalCharge'] = df.groupby('departmentCode').apply(
        lambda x: x['inputCharge'].sum() + x['outputCharge'].sum()
    ).values
    dept_summary = dept_summary.sort_values('totalCharge', ascending=False)
    
    return {
        "overview": {
            "dateRange": date_range,
            "totalCharge": round(total_charge, 2),
            "totalUsers": total_users,
            "totalUsage": total_usage,
        },
        "userSummary": json.loads(user_summary.to_json(orient='records', force_ascii=False)),
        "userModel": json.loads(user_model.to_json(orient='records', force_ascii=False)),
        "userTool": json.loads(user_tool.to_json(orient='records', force_ascii=False)),
        "deptSummary": json.loads(dept_summary.to_json(orient='records', force_ascii=False)),
    }

@app.get("/api/file/{filename}")
def get_raw_file(filename: str, request: Request):
    require_access(request)
    """
    엑셀 원본 파일을 그대로 내려준다.
    새 대시보드(index.html)는 브라우저에서 직접 엑셀을 파싱하기 때문에 이 엔드포인트를 쓴다.
    (기존 /api/data, /api/preview 는 그대로 두어 이전 화면·연동도 계속 동작한다.)
    """
    me = require_access(request)
    path = safe_data_path(filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="파일이 없습니다.")

    # 이 주소는 화면이 데이터를 읽으려고 부르는 곳이다.
    # 직원이 파일을 내려받은 것이 아니다 (화면의 [다운로드] 버튼은
    # 브라우저에서 현재 화면 데이터를 엑셀로 만들 뿐 서버를 거치지 않는다).
    # 그래서 "다운로드"가 아니라 "조회"로 남긴다.
    #
    # 그대로 남기면 목록 화면 한 번 열 때마다 달 수만큼 줄이 쌓인다.
    # 같은 사람이 같은 파일을 다시 보는 것은 잠시 묶어 둔다.
    if not is_trusted_service(request):
        log_view(me, os.path.basename(path))

    # 캐시 금지.
    #
    # 이 주소는 "그 달의 최신 엑셀"이라는 뜻이지 고정된 파일이 아니다.
    # 파일을 새로 올려도 주소가 그대로라, Cache-Control 을 주지 않으면
    # 브라우저가 Last-Modified 를 보고 알아서 "아직 신선하다"고 판단해
    # 서버에 물어보지도 않고 옛 파일로 화면을 그린다.
    # 실제로 7/31 까지 올렸는데 7/22 까지만 나오는 일이 있었다.
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=os.path.basename(path),
        headers={"Cache-Control": "no-store, must-revalidate"},
    )

DENY_PAGE = """<!doctype html><html lang="ko"><meta charset="utf-8">
<title>접근 권한 없음</title>
<body style="margin:0;display:grid;place-items:center;height:100vh;
 font-family:'Pretendard','맑은 고딕',system-ui,sans-serif;background:#f5f6f8;color:#1f2023">
<div style="text-align:center">
  <div style="font-size:17px;font-weight:650;margin-bottom:8px">%s</div>
  <div style="font-size:13px;color:#8a8e97;margin-bottom:20px">%s</div>
  <a href="/" style="display:inline-block;padding:9px 18px;border-radius:9px;
     background:#132033;color:#fff;text-decoration:none;font-size:13.5px">포탈로 돌아가기</a>
</div></body></html>"""

@app.get("/xlsx.min.js")
def xlsx_lib():
    """엑셀을 브라우저에서 읽는 라이브러리 (SheetJS).

    예전에는 index.html 안에 통째로 박혀 있었다. 그래서 화면을 한 줄 고쳐도
    브라우저가 940KB 를 다시 받았다. 파일로 빼서 한 번 받아 두고 쓰게 한다.

    남의 공개 라이브러리라 우리 정보가 없다. 여기서 권한을 따로 묻지 않는다
    (앞단 프록시가 이미 이 앱에 들어올 자격은 확인했다).
    """
    return FileResponse("/app/xlsx.min.js",
                        media_type="application/javascript",
                        headers={"Cache-Control": "public, max-age=604800"})


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    # 화면도 막는다. API 만 막고 화면을 열어두면 빈 대시보드가 떠서
    # "고장났나?" 로 읽힌다. 권한이 없다는 사실을 분명히 알려주는 편이 낫다.
    me = check_access(request)
    if not me.get("logged_in"):
        return HTMLResponse(DENY_PAGE % ("로그인이 필요합니다",
                                         "포탈에서 로그인한 뒤 다시 들어와 주세요."), status_code=401)
    if not me.get("allowed"):
        return HTMLResponse(DENY_PAGE % ("이 서비스를 이용할 권한이 없습니다",
                                         "필요하시면 IT 담당자에게 문의해주세요."), status_code=403)
    return open("/app/index.html", "r", encoding="utf-8").read()
