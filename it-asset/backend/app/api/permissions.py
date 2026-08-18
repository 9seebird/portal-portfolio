"""이 앱 안의 화면 권한.

포털은 "자산관리를 쓸 수 있나"까지만 정한다. 그 안에서 누가 어느 화면을
보는지는 여기서 정한다. 담당자(포털에서 지정)만 이 화면을 쓴다.

권한이 두 곳에 나뉘는 것은 알고 한 선택이다. 자산관리만 이런 요구가
있고(전화 담당이 따로 있다), 다른 앱은 포털의 접근 범위로 충분하다.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_admin
from app.db.database import get_db
from app.models.app_user import AppUser

router = APIRouter(prefix="/permissions", tags=["Permissions"])

# 화면 이름. 화면(app.js)의 nav 와 같아야 한다.
ALL_VIEWS = ["dashboard", "workspace", "seats", "assets",
             "employees", "ips", "extensions", "software", "rentals"]
VIEW_LABELS = {
    "dashboard": "대시보드", "workspace": "직원별 현황", "seats": "자리 배치",
    "assets": "자산 등록", "employees": "직원 명단", "ips": "IP 관리",
    "extensions": "내선 관리", "software": "소프트웨어", "rentals": "렌탈",
}

# 아무것도 안 정해 준 사람이 보는 화면.
# 보는 것만 있고 고치는 것은 없다 — 고치기는 어차피 담당자만 된다.
DEFAULT_VIEWS = ["employees", "seats", "ips", "extensions"]


def clean(views: list[str]) -> list[str]:
    """모르는 이름은 버린다. 화면 이름이 바뀌었을 때 찌꺼기가 남지 않게."""
    seen, out = set(), []
    for v in views or []:
        v = (v or "").strip()
        if v in ALL_VIEWS and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def views_of(db: Session, user) -> list[str]:
    """이 사람이 볼 수 있는 화면. 담당자는 전부 본다."""
    if user.role == "ADMIN":
        return list(ALL_VIEWS)
    row = db.get(AppUser, user.username)
    if row and (row.views or "").strip():
        return clean(row.views.split(","))
    return list(DEFAULT_VIEWS)


def touch(db: Session, user) -> None:
    """들어온 사람을 적어 둔다.

    권한 화면에서 고를 목록이 필요한데, 포털 사용자 목록을 이 앱은 모른다.
    한 번이라도 들어온 사람이면 목록에 뜬다. 아이디를 손으로 받아 적게 하면
    오타 한 번에 권한이 안 먹고, 왜 안 먹는지도 알기 어렵다.
    """
    now = datetime.now(timezone.utc)
    row = db.get(AppUser, user.username)
    if row is None:
        row = AppUser(user_id=user.username,
                      name=getattr(user, "display_name", "") or "",
                      dept=getattr(user, "dept", "") or "",
                      views="")
        db.add(row)
    else:
        # 이름·부서는 포털에서 바뀔 수 있다. 들어올 때마다 최신으로 둔다.
        row.name = getattr(user, "display_name", "") or row.name
        row.dept = getattr(user, "dept", "") or row.dept
    row.last_seen = now
    db.commit()


def require_view(view: str):
    """그 화면을 고칠 수 있는 사람만 통과시킨다.

    **체크한 화면은 보기와 고치기 둘 다** 된다. 보기만 되고 고치기가 안 되면
    전화 담당자가 내선을 못 바꾸니 권한을 준 뜻이 없다.

    화면에서 버튼을 감추는 것은 정리일 뿐이고, 진짜 차단은 여기서 한다.
    """
    def dep(request: Request, db: Session = Depends(get_db)):
        user = get_current_user(request)
        if user.role == "ADMIN":
            return user
        if view in views_of(db, user):
            return user
        raise HTTPException(
            status_code=403,
            detail=f"'{VIEW_LABELS.get(view, view)}' 을(를) 고칠 권한이 없습니다. "
                   "IT 담당자에게 문의해주세요.")
    return dep


class SetViews(BaseModel):
    views: list[str]


@router.get("")
@router.get("/")
def list_people(db: Session = Depends(get_db), _admin=Depends(require_admin)):
    """이 앱에 들어온 적 있는 사람과 각자의 화면 권한."""
    rows = db.query(AppUser).order_by(AppUser.name).all()
    return {
        "views": [{"id": v, "label": VIEW_LABELS[v]} for v in ALL_VIEWS],
        "defaults": DEFAULT_VIEWS,
        "people": [
            {
                "user_id": r.user_id,
                "name": r.name,
                "dept": r.dept,
                "views": clean((r.views or "").split(",")),
                "custom": bool((r.views or "").strip()),
                "last_seen": r.last_seen.isoformat() if r.last_seen else None,
            }
            for r in rows
        ],
    }


@router.put("/{user_id}")
def set_views(user_id: str, body: SetViews,
              db: Session = Depends(get_db), _admin=Depends(require_admin)):
    """그 사람이 볼 화면을 정한다. 빈 목록으로 두면 기본값으로 돌아간다."""
    row = db.get(AppUser, user_id)
    if row is None:
        raise HTTPException(status_code=404,
                            detail="이 앱에 아직 들어온 적 없는 사람입니다. "
                                   "한 번 들어오면 목록에 뜹니다.")
    row.views = ",".join(clean(body.views))
    db.commit()
    return {"user_id": user_id, "views": clean((row.views or "").split(",")),
            "custom": bool(row.views.strip())}
