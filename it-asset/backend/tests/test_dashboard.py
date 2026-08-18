"""대시보드 집계와 만료 임박 알림."""

from datetime import date, timedelta


def test_빈_상태에서는_모두_0이다(admin):
    s = admin.get("/dashboard/summary").json()
    assert s["total_assets"] == 0
    assert s["assigned_assets"] == 0


def test_자산_지급_반납이_집계에_반영된다(admin, make_employee, make_asset):
    emp = make_employee()
    a1 = make_asset(asset_no="A-1")
    make_asset(asset_no="A-2", status="STORAGE")

    admin.post(
        "/asset-assignments/",
        json={"asset_id": a1["id"], "employee_id": emp["id"]},
    )

    s = admin.get("/dashboard/summary").json()
    assert s["total_assets"] == 2
    assert s["assigned_assets"] == 1

    admin.post("/asset-assignments/return", params={"asset_id": a1["id"]})

    s = admin.get("/dashboard/summary").json()
    assert s["assigned_assets"] == 0
    assert s["storage_assets"] == 2


def test_만료_임박_라이선스가_잡힌다(admin):
    """계약 만료를 지나서야 알게 되는 문제를 막는 기능이다."""
    sw = admin.post(
        "/software-products", json={"name": "Microsoft 365", "vendor": "Microsoft"}
    ).json()

    admin.post(
        "/license-pools",
        json={
            "software_id": sw["id"],
            "purchased_count": 80,
            "expire_date": str(date.today() + timedelta(days=20)),  # 30일 이내
        },
    )

    assert len(admin.get("/license-pools/expiring").json()) == 1
    assert admin.get("/dashboard/summary").json()["license_expiring"] == 1


def test_한참_남은_라이선스는_잡히지_않는다(admin):
    sw = admin.post("/software-products", json={"name": "Adobe"}).json()
    admin.post(
        "/license-pools",
        json={
            "software_id": sw["id"],
            "purchased_count": 5,
            "expire_date": str(date.today() + timedelta(days=300)),
        },
    )

    assert admin.get("/license-pools/expiring").json() == []
    assert admin.get("/dashboard/summary").json()["license_expiring"] == 0


def test_만료_임박_렌탈계약이_잡힌다(admin, make_asset):
    asset = make_asset()
    admin.post(
        "/rental-contracts/",
        json={
            "asset_id": asset["id"],
            "vendor": "한빛렌탈",
            "contract_no": "R-2026-01",
            "status": "ACTIVE",
            "end_date": str(date.today() + timedelta(days=45)),  # 60일 이내
        },
    )

    assert len(admin.get("/rental-contracts/expiring").json()) == 1
    assert admin.get("/dashboard/summary").json()["rental_expiring"] == 1


def test_IP_사용률은_등록된_대역_기준으로_계산된다(admin, make_asset):
    """예전에는 분모가 512로 고정돼 있었다."""
    asset = make_asset()
    admin.post(
        "/ip-ranges",
        json={"name": "사무실", "start_ip": "10.0.0.1", "end_ip": "10.0.0.100"},
    )  # 100개
    for i in range(10):
        admin.post(
            "/ip-assignments",
            json={
                "ip_address": f"10.0.0.{i + 1}",
                "asset_id": asset["id"],
                "status": "USED",
            },
        )

    assert admin.get("/dashboard/summary").json()["ip_usage_rate"] == 10


def test_유형별_상태별_분포가_나온다(admin, make_asset):
    make_asset(asset_no="A-1", asset_type="LAPTOP", status="IN_USE")
    make_asset(asset_no="A-2", asset_type="LAPTOP", status="STORAGE")
    make_asset(asset_no="A-3", asset_type="MONITOR", status="STORAGE")

    b = admin.get("/dashboard/breakdown").json()
    by_type = {i["key"]: i["count"] for i in b["by_type"]}
    by_status = {i["key"]: i["count"] for i in b["by_status"]}

    assert by_type["LAPTOP"] == 2
    assert by_type["MONITOR"] == 1
    assert by_status["STORAGE"] == 2
