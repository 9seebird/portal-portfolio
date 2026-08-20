"""테스트 공통 준비물.

pytest 는 conftest.py 를 자동으로 읽는다.
여기서 만든 함수(fixture)는 테스트 파일에서 인자 이름만 적으면 그대로 주입된다.

핵심 원칙: 테스트는 실제 개발/운영 DB를 절대 건드리지 않는다.
매 테스트마다 임시 SQLite 파일을 새로 만들고, 끝나면 지운다.
"""

import os
import tempfile
from pathlib import Path
from urllib.parse import quote

import pytest

# app 을 import 하기 "전에" 환경변수를 세팅해야 한다.
# settings 가 import 시점에 값을 읽어버리기 때문이다.
_TMP_DB = Path(tempfile.gettempdir()) / "asset_portal_test.db"
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{_TMP_DB}"
os.environ["SECRET_KEY"] = "test-only-secret-not-for-production"
os.environ["ALGORITHM"] = "HS256"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "60"
os.environ["PRODUCTION"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

# 주의: `import app.models` 를 `from app.main import app` 뒤에 두면
# 이름 `app` 이 FastAPI 인스턴스에서 패키지 모듈로 덮어써진다.
# 그러면 TestClient(app) 이 모듈을 받아 TypeError 가 난다.
# 모델 등록(import)을 먼저 끝내고, 인스턴스를 마지막에 가져온다.
import app.models  # noqa: E402,F401  (SQLAlchemy 모델 등록용)

from app.db.base import Base  # noqa: E402
from app.db.database import SessionLocal, engine  # noqa: E402
from app.models.user import User  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """테스트 하나마다 빈 DB로 시작한다.

    autouse=True 라서 모든 테스트에 자동 적용된다.
    앞 테스트가 만든 데이터가 뒤 테스트에 영향을 주면
    "혼자 돌리면 통과, 같이 돌리면 실패" 같은 골치 아픈 상황이 생긴다.
    """
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    db = SessionLocal()
    db.add(
        User(
            username="admin",
            # 자체 로그인이 없어지면서 hash_password 가 지워졌다
            # (app/core/security.py 아래 주석 참고). password_hash 는
            # NOT NULL 이라 값은 있어야 하지만, 이 값으로 로그인하는 곳은 없다 —
            # 로그인은 포털이 하고 이 앱은 헤더로 사용자를 받는다.
            password_hash="unused-포털이-로그인을-한다",
            role="ADMIN",
            is_active=True,
        )
    )
    db.commit()
    db.close()

    yield

    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    """아무 헤더도 없는 클라이언트. 앞단(포털)을 거치지 않고 들어온 요청이다."""
    return TestClient(fastapi_app)


# ── 포털이 넣어 주는 헤더 ────────────────────────────────────
#
# 이 앱에는 로그인이 없다. 앞단 nginx 가 포털에 "이 사람이 이걸 써도 되나"를
# 묻고, 통과한 요청에만 아래 헤더를 붙여 넘겨준다 (app/core/security.py).
# 그래서 테스트도 **로그인하는 대신 헤더를 붙인다.**
#
# ★ 헤더에는 latin-1 만 담을 수 있어서 한글은 퍼센트 인코딩해서 넣는다.
#   그냥 "홍길동" 을 넣으면 서버에 닿기도 전에 클라이언트가 터진다.
#   실제 nginx 도 같은 이유로 인코딩해서 보낸다.
def _portal_headers(uid: str, name: str, dept: str, role: str) -> dict:
    return {
        "X-User-Id": uid,
        "X-User-Name": quote(name),
        "X-User-Dept": quote(dept),
        "X-User-Role": role,
    }


@pytest.fixture
def admin(client):
    """담당자로 들어온 클라이언트.

    예전에는 여기서 /auth/login 을 불러 토큰을 받았다. 로그인이 포털로
    옮겨가면서 그 주소가 사라졌고, 픽스처가 404 를 받아 **거의 모든 테스트가
    무너져 있었다** — 코드가 틀린 게 아니라 테스트가 옛 구조를 보고 있었다.
    """
    client.headers.update(_portal_headers("admin", "관리자", "IT팀", "admin"))
    return client


@pytest.fixture
def member(client):
    """담당자가 아닌 일반 직원. 담당자 전용 동작이 막히는지 볼 때 쓴다."""
    client.headers.update(_portal_headers("hong", "홍길동", "인사총무팀", "user"))
    return client


# ---- 테스트 데이터를 간단히 만들기 위한 도우미 ----

@pytest.fixture
def make_employee(admin):
    def _make(emp_no="E001", name="홍길동", **kw):
        payload = {"emp_no": emp_no, "name": name, "status": "ACTIVE", **kw}
        res = admin.post("/employees/", json=payload)
        assert res.status_code == 200, res.text
        return res.json()

    return _make


@pytest.fixture
def make_asset(admin):
    def _make(asset_no="NB-0001", asset_type="LAPTOP", **kw):
        payload = {"asset_no": asset_no, "asset_type": asset_type, **kw}
        res = admin.post("/assets/", json=payload)
        assert res.status_code == 200, res.text
        return res.json()

    return _make


@pytest.fixture
def make_seat():
    """자리를 DB 에 직접 넣는다.

    자리 만들기 API 를 거치면 좌표 겹침 검사에 걸려서, 자리 자체가 목적이 아닌
    테스트(내선번호 등)에서 번거로워진다.
    """
    import uuid

    from app.db.database import SessionLocal
    from app.models.seat import Seat

    def _make(floor="3층", row=1, col=1, kind="DESK", label="자리", **kw):
        db = SessionLocal()
        try:
            seat = Seat(id=uuid.uuid4(), floor=floor, row_idx=row, col_idx=col,
                        kind=kind, label=label, **kw)
            db.add(seat)
            db.commit()
            return str(seat.id)
        finally:
            db.close()

    return _make


@pytest.fixture
def query_counter():
    """이 픽스처를 받는 테스트 동안 실행된 SQL 문 수를 센다.

    N+1 회귀를 잡는 용도. 원래 test_performance.py 안에 있었는데
    자리 배치 테스트에서도 필요해져서 공용으로 옮겼다.
    """
    from sqlalchemy import event

    counter = {"n": 0}

    def count(conn, cursor, statement, params, context, executemany):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", count)
    yield counter
    event.remove(engine, "before_cursor_execute", count)
