"""라이선스 부여 / 회수.

요구사항은 세 가지다.
  1. 개별 부여    — 중간에 한 사람에게 라이선스를 줄 수 있어야 한다
  2. 개별 회수    — 퇴사와 무관하게 라이선스만 뺄 수 있어야 한다
  3. 퇴사 시 자동 회수 — 퇴사 처리하면 보유 라이선스가 전부 반납되어야 한다

3번이 안 되면 퇴사자가 계속 자리를 차지해서
실제보다 사용 수량이 부풀어 오르고, 결국 라이선스를 더 사게 된다.
"""

import pytest


@pytest.fixture
def pool(admin):
    """보유 2자리짜리 라이선스."""
    sw = admin.post(
        "/software-products", json={"name": "Creative Cloud", "vendor": "Adobe"}
    ).json()
    return admin.post(
        "/license-pools", json={"software_id": sw["id"], "purchased_count": 2}
    ).json()


def usage(admin):
    return admin.get("/license-assignments/usage").json()[0]


def test_라이선스를_직원에게_부여한다(admin, pool, make_employee):
    emp = make_employee()

    res = admin.post(
        "/license-assignments/",
        json={"license_pool_id": pool["id"], "employee_id": emp["id"]},
    )

    assert res.status_code == 200
    assert res.json()["employee_name"] == emp["name"]
    assert res.json()["released_at"] is None
    assert usage(admin)["used_count"] == 1


def test_같은_사람에게_같은_라이선스를_두번_주지_않는다(admin, pool, make_employee):
    emp = make_employee()
    body = {"license_pool_id": pool["id"], "employee_id": emp["id"]}
    admin.post("/license-assignments/", json=body)

    res = admin.post("/license-assignments/", json=body)

    assert res.status_code == 409
    assert usage(admin)["used_count"] == 1


def test_퇴사시키지_않고_라이선스만_회수한다(admin, pool, make_employee):
    """직원은 계속 재직 중인데 라이선스만 빼는 경우."""
    emp = make_employee()
    a = admin.post(
        "/license-assignments/",
        json={"license_pool_id": pool["id"], "employee_id": emp["id"]},
    ).json()

    res = admin.post(f"/license-assignments/{a['id']}/release")

    assert res.status_code == 200
    assert res.json()["release_reason"] == "MANUAL"
    assert usage(admin)["used_count"] == 0
    # 직원은 그대로 재직 상태여야 한다
    assert admin.get(f"/employees/{emp['id']}").json()["status"] == "ACTIVE"


def test_이미_회수한_라이선스는_다시_회수되지_않는다(admin, pool, make_employee):
    emp = make_employee()
    a = admin.post(
        "/license-assignments/",
        json={"license_pool_id": pool["id"], "employee_id": emp["id"]},
    ).json()
    admin.post(f"/license-assignments/{a['id']}/release")

    res = admin.post(f"/license-assignments/{a['id']}/release")

    assert res.status_code == 409


def test_부여id를_몰라도_직원과_라이선스로_회수할_수_있다(admin, pool, make_employee):
    emp = make_employee()
    admin.post(
        "/license-assignments/",
        json={"license_pool_id": pool["id"], "employee_id": emp["id"]},
    )

    res = admin.post(
        "/license-assignments/release-by-pair",
        params={"employee_id": emp["id"], "license_pool_id": pool["id"]},
    )

    assert res.status_code == 200
    assert usage(admin)["used_count"] == 0


def test_퇴사하면_라이선스가_자동으로_회수된다(admin, pool, make_employee):
    """[핵심] 이게 안 되면 퇴사자가 계속 라이선스를 물고 있는다."""
    emp = make_employee()
    admin.post(
        "/license-assignments/",
        json={"license_pool_id": pool["id"], "employee_id": emp["id"]},
    )
    assert usage(admin)["used_count"] == 1

    res = admin.post(f"/employees/{emp['id']}/offboard")

    assert res.json()["released_licenses"] == 1
    assert usage(admin)["used_count"] == 0

    history = admin.get(
        "/license-assignments/",
        params={"employee_id": emp["id"], "active_only": False},
    ).json()
    assert history[0]["release_reason"] == "OFFBOARD"


def test_퇴사자에게는_라이선스를_부여할_수_없다(admin, pool, make_employee):
    emp = make_employee()
    admin.post(f"/employees/{emp['id']}/offboard")

    res = admin.post(
        "/license-assignments/",
        json={"license_pool_id": pool["id"], "employee_id": emp["id"]},
    )

    assert res.status_code == 400


def test_보유수량을_넘으면_초과로_표시된다(admin, pool, make_employee):
    """등록 자체를 막지는 않는다.
    이미 초과 상태인 현실을 담아야 하고, 막으면 실제 현황을 기록할 수 없다.
    대신 현황 조회에서 초과로 잡아준다."""
    for i in range(3):  # 보유는 2자리
        emp = make_employee(emp_no=f"E{i}", name=f"직원{i}")
        admin.post(
            "/license-assignments/",
            json={"license_pool_id": pool["id"], "employee_id": emp["id"]},
        )

    u = usage(admin)
    assert u["used_count"] == 3
    assert u["available_count"] == -1
    assert u["is_over_allocated"] is True


def test_사용중인_부여만_조회할_수_있다(admin, pool, make_employee):
    emp1 = make_employee(emp_no="E1", name="홍길동")
    emp2 = make_employee(emp_no="E2", name="김철수")
    a1 = admin.post(
        "/license-assignments/",
        json={"license_pool_id": pool["id"], "employee_id": emp1["id"]},
    ).json()
    admin.post(
        "/license-assignments/",
        json={"license_pool_id": pool["id"], "employee_id": emp2["id"]},
    )
    admin.post(f"/license-assignments/{a1['id']}/release")

    active = admin.get("/license-assignments/").json()
    everything = admin.get(
        "/license-assignments/", params={"active_only": False}
    ).json()

    assert len(active) == 1
    assert active[0]["employee_name"] == "김철수"
    assert len(everything) == 2


# ---- 소프트웨어·라이선스 삭제와 부여 이력 ----
#
# license_assignments 가 license_pools 를 참조한다.
# 이력을 남긴 채 보유를 지우면 외래키 위반으로 500 이 났었다.
# 무엇이 걸려 있는지 알려주고 막되, 원하면 이력까지 지울 수 있어야 한다.

def test_부여_이력이_있으면_소프트웨어를_바로_못_지운다(admin, pool, make_employee):
    emp = make_employee()
    admin.post("/license-assignments/",
               json={"license_pool_id": pool["id"], "employee_id": emp["id"]})

    res = admin.delete(f"/software-products/{pool['software_id']}")

    assert res.status_code == 409
    assert "1건" in res.json()["detail"]
    assert "보유 중 1명" in res.json()["detail"]


def test_회수한_이력만_있어도_알려준다(admin, pool, make_employee):
    emp = make_employee()
    created = admin.post("/license-assignments/",
                         json={"license_pool_id": pool["id"], "employee_id": emp["id"]}).json()
    admin.post(f"/license-assignments/{created['id']}/release")

    res = admin.delete(f"/software-products/{pool['software_id']}")

    assert res.status_code == 409
    # 지금 보유한 사람은 없으므로 그 문구는 빠진다
    assert "보유 중" not in res.json()["detail"]


def test_force_로_이력까지_지운다(admin, pool, make_employee):
    emp = make_employee()
    admin.post("/license-assignments/",
               json={"license_pool_id": pool["id"], "employee_id": emp["id"]})

    res = admin.delete(f"/software-products/{pool['software_id']}?force=true")

    assert res.status_code == 200
    assert admin.get("/license-assignments/").json() == []
    assert admin.get("/license-pools").json() == []


def test_라이선스_보유도_이력이_있으면_막는다(admin, pool, make_employee):
    emp = make_employee()
    admin.post("/license-assignments/",
               json={"license_pool_id": pool["id"], "employee_id": emp["id"]})

    blocked = admin.delete(f"/license-pools/{pool['id']}")
    forced = admin.delete(f"/license-pools/{pool['id']}?force=true")

    assert blocked.status_code == 409
    assert forced.status_code == 200


def test_이력이_없으면_그냥_지워진다(admin, pool):
    res = admin.delete(f"/software-products/{pool['software_id']}")

    assert res.status_code == 200
