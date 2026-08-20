"""인증 · 권한.

이 앱에는 로그인이 없다. 앞단 nginx 가 포털에 물어보고, 통과한 요청에만
X-User-* 헤더를 붙여 넘겨준다 (app/core/security.py).

그래서 여기서 볼 것은 「비밀번호가 맞는가」가 아니라 이 세 가지다.

    헤더가 없으면 들여보내지 않는가
    헤더가 있으면 그 사람으로 보는가
    담당자가 아니면 담당자 전용 동작이 막히는가

★ 「헤더를 위조하면 어떻게 되나」는 여기서 시험하지 않는다.
  이 앱은 헤더를 그대로 믿는 것이 **설계**다. 위조를 막는 것은 앞단 nginx 의
  일이고(직원이 X-User-Role: admin 을 붙여 보내도 덮어쓴다), 그건 이 앱의
  테스트로는 확인할 수 없다. 여기서 400 을 기대하도록 써 두면 「막고 있다」는
  착각만 남는다.
"""

from urllib.parse import quote


def test_헬스체크는_로그인_없이_열린다(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_헤더_없이_보호된_API를_부르면_401(client):
    assert client.get("/dashboard/summary").status_code == 401
    assert client.get("/assets/").status_code == 401
    assert client.get("/employees/").status_code == 401


def test_포털_헤더를_붙이면_통과한다(admin):
    assert admin.get("/dashboard/summary").status_code == 200
    assert admin.get("/assets/").status_code == 200


def test_내_정보는_헤더를_그대로_돌려준다(admin):
    res = admin.get("/auth/me")
    assert res.status_code == 200
    body = res.json()
    assert body["username"] == "admin"
    assert body["role"] == "ADMIN"
    # 볼 수 있는 화면 목록도 같이 온다. 화면이 이걸 보고 메뉴를 그린다.
    assert isinstance(body["views"], list)


def test_담당자가_아니면_role_이_USER(member):
    res = member.get("/auth/me")
    assert res.status_code == 200
    assert res.json()["role"] == "USER"


def test_담당자가_아니면_담당자_전용_API는_403(member):
    assert member.get("/permissions/").status_code == 403


def test_담당자면_담당자_전용_API가_열린다(admin):
    assert admin.get("/permissions/").status_code == 200


def test_한글_이름은_퍼센트_인코딩되어_온다(client):
    """헤더에는 latin-1 만 담긴다. 포털도 인코딩해서 보내고, 앱이 풀어서 읽는다.

    이걸 놓치면 화면 오른쪽 위 이름이 %ED%99%8D... 로 뜬다.
    """
    client.headers.update({
        "X-User-Id": "hong",
        "X-User-Name": quote("홍길동"),
        "X-User-Dept": quote("인사총무팀"),
        "X-User-Role": "user",
    })
    assert client.get("/auth/me").status_code == 200
