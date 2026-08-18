"""직원 삭제 가드.

원칙: 퇴사자는 삭제하지 않고 offboard 로 INACTIVE 처리해 이력을 남긴다.
삭제는 오타·중복 등록 같은 '잘못 넣은 데이터 정리용'이다.

예전에는 삭제가 지급 이력을 통째로 지웠고,
license_assignments 가 생긴 뒤로는 FK 때문에 500이 날 수 있었다.
지금은 이력이 있으면 409 로 막고, force=true 일 때만 이력째 지운다.
"""


def test_이력이_없는_직원은_바로_삭제된다(admin, make_employee):
    emp = make_employee()

    res = admin.delete(f"/employees/{emp['id']}")

    assert res.status_code == 200
    assert admin.get(f"/employees/{emp['id']}").status_code == 404


def test_지급_이력이_있으면_삭제가_막힌다(admin, make_employee, make_asset):
    emp = make_employee()
    asset = make_asset()
    admin.post(
        "/asset-assignments/",
        json={"asset_id": asset["id"], "employee_id": emp["id"]},
    )
    # 반납까지 해서 '활성 지급은 없지만 이력은 남은' 상태를 만든다
    admin.post("/asset-assignments/return", params={"asset_id": asset["id"]})

    res = admin.delete(f"/employees/{emp['id']}")

    assert res.status_code == 409
    # 직원은 그대로 남아 있어야 한다
    assert admin.get(f"/employees/{emp['id']}").status_code == 200


def test_라이선스_이력이_있으면_삭제가_막힌다(admin, make_employee):
    emp = make_employee()
    sw = admin.post("/software-products", json={"name": "M365"}).json()
    pool = admin.post(
        "/license-pools", json={"software_id": sw["id"], "purchased_count": 5}
    ).json()
    a = admin.post(
        "/license-assignments/",
        json={"license_pool_id": pool["id"], "employee_id": emp["id"]},
    ).json()
    admin.post(f"/license-assignments/{a['id']}/release")

    res = admin.delete(f"/employees/{emp['id']}")

    assert res.status_code == 409


def test_force면_라이선스_이력까지_지우고_삭제된다(admin, make_employee):
    """잘못 등록한 직원 정리용. 500이 나지 않아야 한다."""
    emp = make_employee()
    sw = admin.post("/software-products", json={"name": "M365"}).json()
    pool = admin.post(
        "/license-pools", json={"software_id": sw["id"], "purchased_count": 5}
    ).json()
    admin.post(
        "/license-assignments/",
        json={"license_pool_id": pool["id"], "employee_id": emp["id"]},
    )

    res = admin.delete(f"/employees/{emp['id']}", params={"force": True})

    assert res.status_code == 200
    assert admin.get(f"/employees/{emp['id']}").status_code == 404
    # 고아 레코드가 남지 않아야 한다
    rows = admin.get(
        "/license-assignments/",
        params={"employee_id": emp["id"], "active_only": False},
    ).json()
    assert rows == []
