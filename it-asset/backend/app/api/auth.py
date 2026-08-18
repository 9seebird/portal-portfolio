"""로그인 관련 — 자체 로그인은 없어졌다.

/auth/login 을 지웠다. 로그인은 포털이 한다.
/auth/me 는 남겨 둔다. 화면(app.js)이 시작할 때 이걸 불러
"지금 누가 보고 있는지"와 담당자 여부를 확인하기 때문이다.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.permissions import touch, views_of
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.auth import MeResponse

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """지금 접속한 사람. 포털이 넘겨준 헤더를 그대로 돌려준다.

    화면은 role 이 ADMIN 인지 보고 삭제 버튼을 켜고 끈다.
    진짜 차단은 각 API 의 require_admin 이 한다.

    여기서 두 가지를 더 한다.
      · 들어온 사람을 적어 둔다 — 권한 화면에서 고를 목록이 된다
      · 볼 수 있는 화면 목록을 함께 준다 — 화면이 그걸 보고 메뉴를 그린다

    권한 표가 아직 없어도(마이그레이션 전) 앱은 떠야 한다. 그래서 실패하면
    기본값으로 넘어간다. 첫 화면이 통째로 안 뜨는 것보다 낫다.
    """
    views = []
    try:
        touch(db, user)
        views = views_of(db, user)
    except Exception as error:  # noqa: BLE001
        db.rollback()
        print(f"[경고] 화면 권한을 읽지 못했습니다: {error}\n"
              "        alembic upgrade head 를 돌렸는지 확인하세요.", flush=True)
        from app.api.permissions import ALL_VIEWS, DEFAULT_VIEWS
        views = list(ALL_VIEWS if user.role == "ADMIN" else DEFAULT_VIEWS)
    return MeResponse(username=user.username, role=user.role, views=views)
