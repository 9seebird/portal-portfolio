"""퇴사 처리.

연간 체크리스트의 "퇴사자 계정 비활성화 / 자산 회수" 항목을
자동화한 부분이라 이 프로젝트에서 가장 중요한 기능이다.
빠뜨리면 실제로 회사에 자산 분실과 IP 낭비가 생긴다.
"""


def test_퇴사하면_보유자산이_전부_회수된다(admin, make_employee, make_asset):
    emp = make_employee()
    노트북 = make_asset(asset_no="NB-1", asset_type="LAPTOP")
    모니터 = make_asset(asset_no="MON-1", asset_type="MONITOR")

    for a in (노트북, 모니터):
        admin.post(
            "/asset-assignments/",
            json={"asset_id": a["id"], "employee_id": emp["id"]},
        )

    res = admin.post(f"/employees/{emp['id']}/offboard")

    assert res.status_code == 200
    assert res.json()["returned_assets"] == 2
    for a in (노트북, 모니터):
        assert admin.get(f"/assets/{a['id']}").json()["status"] == "STORAGE"


def test_퇴사하면_할당된_IP가_해제된다(admin, make_employee, make_asset):
    emp = make_employee()
    asset = make_asset()
    admin.post(
        "/asset-assignments/",
        json={"asset_id": asset["id"], "employee_id": emp["id"]},
    )
    admin.post(
        "/ip-ranges",
        json={"name": "사무실", "start_ip": "10.0.0.1", "end_ip": "10.0.0.254"},
    )
    admin.post(
        "/ip-assignments",
        json={"ip_address": "10.0.0.50", "asset_id": asset["id"], "status": "USED"},
    )

    res = admin.post(f"/employees/{emp['id']}/offboard")

    assert res.json()["released_ips"] == 1
    ips = admin.get("/ip-assignments").json()
    ips = ips["items"] if isinstance(ips, dict) else ips
    assert all(i["status"] == "FREE" for i in ips)


def test_퇴사하면_상태와_퇴사일이_기록된다(admin, make_employee):
    emp = make_employee()

    admin.post(f"/employees/{emp['id']}/offboard")

    after = admin.get(f"/employees/{emp['id']}").json()
    assert after["status"] == "INACTIVE"
    assert after["resign_date"] is not None


def test_자산이_없는_직원도_퇴사처리된다(admin, make_employee):
    emp = make_employee()
    res = admin.post(f"/employees/{emp['id']}/offboard")
    assert res.status_code == 200
    assert res.json()["returned_assets"] == 0


def test_없는_직원을_퇴사처리하면_404(admin):
    res = admin.post(
        "/employees/00000000-0000-0000-0000-000000000000/offboard"
    )
    assert res.status_code == 404
