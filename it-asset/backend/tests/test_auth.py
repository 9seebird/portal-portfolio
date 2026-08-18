"""인증 · 권한."""


def test_헬스체크는_로그인_없이_열린다(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_올바른_계정으로_로그인하면_토큰을_받는다(client):
    res = client.post(
        "/auth/login", json={"username": "admin", "password": "admin1234"}
    )
    assert res.status_code == 200
    assert res.json()["access_token"]


def test_비밀번호가_틀리면_401(client):
    res = client.post(
        "/auth/login", json={"username": "admin", "password": "틀린비번"}
    )
    assert res.status_code == 401


def test_없는_계정이면_401(client):
    res = client.post(
        "/auth/login", json={"username": "nobody", "password": "admin1234"}
    )
    assert res.status_code == 401


def test_토큰_없이_보호된_API를_부르면_401(client):
    assert client.get("/dashboard/summary").status_code == 401
    assert client.get("/assets/").status_code == 401
    assert client.get("/employees/").status_code == 401


def test_위조된_토큰은_거부된다(client):
    # HTTP 헤더에는 latin-1 만 담을 수 있어서 한글을 넣으면 서버에 닿기도 전에
    # 클라이언트가 터진다. 검증 대상은 서버이므로 값은 ASCII 로 쓴다.
    client.headers.update({"Authorization": "Bearer not-a-real-token"})
    assert client.get("/dashboard/summary").status_code == 401


def test_내_정보_조회(admin):
    res = admin.get("/auth/me")
    assert res.status_code == 200
    assert res.json()["username"] == "admin"
    assert res.json()["role"] == "ADMIN"
