"""자산 지급 · 반납.

이 파일의 첫 테스트가 이번 리뷰에서 찾은 버그를 잡는 '회귀 테스트'다.
회귀(regression)란 "고쳤던 게 나중에 다시 망가지는 것"을 말한다.
테스트를 남겨두면 같은 버그가 되살아나는 순간 바로 빨간불이 켜진다.
"""


def test_자산_지급이_500으로_죽지_않는다(admin, make_employee, make_asset):
    """[회귀] asset_assignments.py 에서 정의되지 않은 변수 asset_id 를 참조해
    POST /asset-assignments/ 가 호출할 때마다 NameError 로 500이 나던 버그.

    수정 전에는 이 테스트가 반드시 실패한다.
    """
    emp = make_employee()
    asset = make_asset()

    res = admin.post(
        "/asset-assignments/",
        json={"asset_id": asset["id"], "employee_id": emp["id"]},
    )

    assert res.status_code == 200, f"지급 API가 실패했다: {res.text}"
    assert res.json()["returned_at"] is None


def test_지급하면_자산상태가_사용중으로_바뀐다(admin, make_employee, make_asset):
    emp = make_employee()
    asset = make_asset(status="STORAGE")

    admin.post(
        "/asset-assignments/",
        json={"asset_id": asset["id"], "employee_id": emp["id"]},
    )

    assert admin.get(f"/assets/{asset['id']}").json()["status"] == "IN_USE"


def test_같은_자산을_다른_사람에게_주면_기존_지급이_자동_반납된다(
    admin, make_employee, make_asset
):
    """한 대의 자산이 동시에 두 사람에게 지급된 상태로 남으면 안 된다.
    앞서 고친 버그가 바로 이 로직에 있었다."""
    emp1 = make_employee(emp_no="E001", name="홍길동")
    emp2 = make_employee(emp_no="E002", name="김철수")
    asset = make_asset()

    admin.post(
        "/asset-assignments/",
        json={"asset_id": asset["id"], "employee_id": emp1["id"]},
    )
    admin.post(
        "/asset-assignments/",
        json={"asset_id": asset["id"], "employee_id": emp2["id"]},
    )

    active = admin.get(
        "/asset-assignments/", params={"asset_id": asset["id"], "active_only": True}
    ).json()

    assert len(active) == 1, "활성 지급은 항상 한 건이어야 한다"
    assert active[0]["employee_id"] == emp2["id"]

    전체 = admin.get(
        "/asset-assignments/", params={"asset_id": asset["id"]}
    ).json()
    assert len(전체) == 2  # 이력은 둘 다 남는다


def test_반납하면_보관상태가_된다(admin, make_employee, make_asset):
    emp = make_employee()
    asset = make_asset()
    admin.post(
        "/asset-assignments/",
        json={"asset_id": asset["id"], "employee_id": emp["id"]},
    )

    res = admin.post("/asset-assignments/return", params={"asset_id": asset["id"]})

    assert res.status_code == 200
    assert res.json()["returned_at"] is not None
    assert admin.get(f"/assets/{asset['id']}").json()["status"] == "STORAGE"


def test_없는_자산을_지급하려_하면_404(admin, make_employee):
    emp = make_employee()
    res = admin.post(
        "/asset-assignments/",
        json={
            "asset_id": "00000000-0000-0000-0000-000000000000",
            "employee_id": emp["id"],
        },
    )
    assert res.status_code == 404


def test_없는_직원에게_지급하려_하면_404(admin, make_asset):
    asset = make_asset()
    res = admin.post(
        "/asset-assignments/",
        json={
            "asset_id": asset["id"],
            "employee_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert res.status_code == 404
