import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRET = "change-me"

# .../it-asset-portal/backend  와  .../it-asset-portal
BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    # 기본값은 로컬 개발용. 운영에서는 .env 또는 환경변수로 반드시 덮어쓴다.
    DATABASE_URL: str = "postgresql+psycopg://asset_user:asset_password@localhost:5432/asset_portal"

    # SQLite 저널 모드. 리눅스 실제 파일시스템이면 WAL 이 빠르지만,
    # Docker Desktop(Windows/macOS) 바인드 마운트 위에서는 WAL 이 깨진다
    # ("database disk image is malformed"). 그 경우 DELETE 로 둔다.
    SQLITE_JOURNAL_MODE: str = "WAL"

    SECRET_KEY: str = INSECURE_SECRET
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # 운영 배포 여부. true 면 안전하지 않은 설정으로는 기동하지 않는다.
    PRODUCTION: bool = False

    # 브라우저에서 접근을 허용할 출처. 쉼표로 구분.
    #   예) CORS_ORIGINS=https://it.example.com
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # 절대경로로 지정한다. 상대경로("` .env `")면 명령을 어느 폴더에서 실행했느냐에 따라
    # .env 를 못 찾고 조용히 기본값으로 떨어진다.
    model_config = SettingsConfigDict(env_file=BACKEND_ROOT / ".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


def _resolve_sqlite_url(url: str) -> str:
    """SQLite 경로를 저장소 기준 절대경로로 바꾸고, 폴더가 없으면 만든다.

    이유 두 가지.
      1) 상대경로는 실행 위치에 따라 다른 파일을 가리킨다.
         backend 에서 돌리면 backend/data/app.db, 저장소 루트에서 돌리면 data/app.db 가
         되어 "데이터가 사라졌다" 로 보인다. 항상 <저장소>/data/app.db 를 가리키게 고정한다.
      2) 폴더가 없으면 SQLite 는 "unable to open database file" 이라는,
         원인을 알 수 없는 메시지만 낸다.
    """
    if not url.startswith("sqlite"):
        return url

    prefix, _, raw = url.partition(":///")
    if not raw or raw == ":memory:":
        return url

    path = Path(raw)
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()

    path.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}:///{path.as_posix()}"


settings = Settings()
settings.DATABASE_URL = _resolve_sqlite_url(settings.DATABASE_URL)

# 운영인데 기본 시크릿을 그대로 쓰면 누구나 관리자 토큰을 위조할 수 있다.
# 조용히 넘어가면 사고로 이어지므로 아예 기동을 막는다.
if settings.PRODUCTION and settings.SECRET_KEY == INSECURE_SECRET:
    sys.exit(
        "[설정 오류] PRODUCTION=true 인데 SECRET_KEY가 기본값입니다.\n"
        "  .env 에 충분히 긴 임의 문자열을 넣으세요:\n"
        '  python -c "import secrets; print(secrets.token_urlsafe(48))"'
    )
