"""쿼리 수 회귀 테스트.

기능 테스트는 '답이 맞는지'만 보고 '몇 번 물어봤는지'는 보지 않는다.
라이선스 목록이 행마다 쿼리를 날리던(N+1) 코드는 기능 테스트 56개를
전부 통과하고도 실데이터 127건에서 요청당 쿼리 256개를 만들어
화면을 눈에 띄게 느리게 했다. (2026-07-28, 실측 256 → 2)

그래서 여기서는 실행된 SQL 문 수를 직접 센다.
데이터가 늘어도 쿼리 수는 상수여야 한다 — 행 수에 비례하기 시작하면
N+1 이 되살아난 것이다.
"""

def seed_assignments(admin, make_employee, people):
    sw = admin.post("/software-products", json={"name": "M365"}).json()
    pool = admin.post(
        "/license-pools", json={"software_id": sw["id"], "purchased_count": 100}
    ).json()
    for i in range(people):
        emp = make_employee(emp_no=f"P{i:03d}", name=f"직원{i}")
        admin.post(
            "/license-assignments/",
            json={"license_pool_id": pool["id"], "employee_id": emp["id"]},
        )


def test_라이선스_목록은_행수와_무관하게_쿼리가_일정하다(
    admin, make_employee, query_counter
):
    seed_assignments(admin, make_employee, people=25)

    query_counter["n"] = 0
    res = admin.get("/license-assignments/")

    assert res.status_code == 200
    assert len(res.json()) == 25
    # 정상: 인증 1 + 본 조회 1. 여유를 줘도 5를 넘을 이유가 없다.
    # N+1 이 되돌아오면 25건 기준 50개를 훌쩍 넘어 바로 잡힌다.
    assert query_counter["n"] <= 5, (
        f"결과 25건에 쿼리 {query_counter['n']}개 — N+1 이 되살아난 듯하다. "
        "행마다 추가 조회를 하고 있지 않은지 확인할 것."
    )


def test_사용현황은_풀_수와_무관하게_쿼리가_일정하다(
    admin, make_employee, query_counter
):
    seed_assignments(admin, make_employee, people=10)

    query_counter["n"] = 0
    res = admin.get("/license-assignments/usage")

    assert res.status_code == 200
    assert query_counter["n"] <= 5, (
        f"쿼리 {query_counter['n']}개 — 풀마다 따로 세고 있지 않은지 확인할 것."
    )


def test_직원별_현황도_직원수와_무관하게_쿼리가_일정하다(
    admin, make_employee, make_asset, query_counter
):
    """원래부터 잘 짜여 있던(IN 절) 엔드포인트가 퇴보하지 않는지도 지킨다."""
    for i in range(15):
        emp = make_employee(emp_no=f"W{i:03d}", name=f"현황{i}")
        asset = make_asset(asset_no=f"NB-{i:04d}")
        admin.post(
            "/asset-assignments/",
            json={"asset_id": asset["id"], "employee_id": emp["id"]},
        )

    query_counter["n"] = 0
    res = admin.get("/employees/workspace")

    assert res.status_code == 200
    assert query_counter["n"] <= 8, (
        f"쿼리 {query_counter['n']}개 — workspace 가 직원/자산마다 "
        "추가 조회를 하기 시작한 듯하다."
    )
