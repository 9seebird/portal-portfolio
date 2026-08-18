"""이 앱에 들어온 사람과, 그 사람이 볼 수 있는 화면.

계정 자체는 포털이 갖고 있다. 여기 있는 것은 **이 앱 안에서의 권한**뿐이다.

왜 앱 안에 두는가
────────────────
포털은 "이 서비스를 쓸 수 있나"까지만 정한다. 그 안에서 "내선은 고치고
자산은 못 고친다" 같은 것은 이 앱에만 있는 이야기다. 포털에 그런 칸을
만들면 앱마다 다른 구역 이름이 포털에 쌓인다.

누구를 고르나
────────────
포털 사용자 목록을 이 앱은 모른다. 그래서 **한 번이라도 들어온 사람**을
여기 적어 두고, 권한 화면에서 그 목록에서 고른다. 아이디를 손으로 받아
적으면 오타 한 번에 권한이 안 먹고 왜 그런지도 알기 어렵다.
"""

from sqlalchemy import Column, String, TIMESTAMP, Text
from sqlalchemy.sql import func

from app.db.base import Base


class AppUser(Base):
    __tablename__ = "app_users"

    # 포털 아이디. 이 앱에는 계정이 없으므로 이것이 곧 사람의 열쇠다.
    user_id = Column(String(64), primary_key=True)

    name = Column(String(100), nullable=False, default="")
    dept = Column(String(100), nullable=False, default="")

    # 볼 수 있는 화면. 쉼표로 이어 둔다 ("employees,seats,ips").
    # 비어 있으면 기본값(모두에게 열린 화면)을 쓴다.
    #
    # JSON 이 아니라 문자열인 이유: SQLite 와 Postgres 양쪽에서 같게 돌고,
    # 값이 짧아 굳이 형식을 따질 일이 없다.
    views = Column(Text, nullable=False, default="")

    first_seen = Column(TIMESTAMP(timezone=True), server_default=func.now())
    last_seen = Column(TIMESTAMP(timezone=True), server_default=func.now())
