from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    """화면이 시작할 때 이걸 보고 메뉴를 그린다.

    views 는 **이 사람이 볼 수 있는 화면 이름들**이다. 화면에 목록을 박아 두면
    권한을 바꿀 때마다 화면 파일을 고쳐 배포해야 한다.
    """
    username: str
    role: str
    views: list[str] = []
