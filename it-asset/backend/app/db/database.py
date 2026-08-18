import sys

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.settings import settings

engine = create_engine(settings.DATABASE_URL)

# SQLite 설정.
#  - journal_mode: WAL 이면 쓰는 중에도 읽기가 막히지 않아 빠르다.
#    다만 WAL 은 공유 메모리 파일(-shm)을 메모리 매핑해야 하는데,
#    Docker Desktop(Windows/macOS)의 바인드 마운트는 그걸 제대로 지원하지 않는다.
#    그 위에서 WAL 을 켜면 "database disk image is malformed" 로 죽는다.
#    그래서 컨테이너에서는 DELETE 로 내리고, 리눅스 서버의 실제 파일시스템에서는
#    WAL 을 쓴다. 값은 .env 의 SQLITE_JOURNAL_MODE 로 정한다.
#  - foreign_keys: SQLite 는 FK 제약이 기본 꺼짐이라 켜줘야 잘못된 참조를 막는다.
# Postgres 에서는 이 블록이 그냥 지나간다.
if engine.url.get_backend_name() == "sqlite":
    _journal = (settings.SQLITE_JOURNAL_MODE or "WAL").strip().upper()

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        try:
            # 저널 모드 변경이 실패해도 앱은 떠야 한다. 여기서 예외가 나가면
            # 연결 자체가 끊겨서 원인을 알기 어려운 스택만 잔뜩 찍힌다.
            cursor.execute(f"PRAGMA journal_mode={_journal}")
        except Exception as error:  # noqa: BLE001
            print(
                f"[경고] SQLite journal_mode={_journal} 설정 실패: {error}\n"
                "        도커 바인드 마운트라면 SQLITE_JOURNAL_MODE=DELETE 로 두세요.",
                file=sys.stderr,
                flush=True,
            )
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
