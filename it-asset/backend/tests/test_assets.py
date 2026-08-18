"""자산 등록과 값 검증."""

import pytest


def test_자산을_등록하고_다시_조회한다(admin, make_asset):
    asset = make_asset(asset_no="NB-0001", asset_type="LAPTOP")
    res = admin.get(f"/assets/{asset['id']}")
    assert res.status_code == 200
    assert res.json()["asset_no"] == "NB-0001"


@pytest.mark.parametrize(
    "asset_type", ["LAPTOP", "DESKTOP", "MONITOR", "SERVER", "NETWORK", "OTHER"]
)
def test_정해진_자산유형은_모두_통과한다(admin, asset_type):
    res = admin.post(
        "/assets/", json={"asset_no": f"A-{asset_type}", "asset_type": asset_type}
    )
    assert res.status_code == 200, res.text


@pytest.mark.parametrize("bad", ["PC", "노트북", "laptop", "COMPUTER", ""])
def test_정해지지_않은_자산유형은_거부된다(admin, bad):
    """예전에는 아무 문자열이나 저장돼서
    화면에 영문 원문이 그대로 노출되고 집계도 따로 잡혔다."""
    res = admin.post("/assets/", json={"asset_no": "X-1", "asset_type": bad})
    assert res.status_code == 422


@pytest.mark.parametrize("bad", ["BROKEN", "사용중", "in_use"])
def test_정해지지_않은_상태값은_거부된다(admin, bad):
    res = admin.post(
        "/assets/",
        json={"asset_no": "X-2", "asset_type": "LAPTOP", "status": bad},
    )
    assert res.status_code == 422


def test_예전에_들어간_규격밖_값이_있어도_목록조회가_죽지_않는다(admin, make_asset):
    """쓰기는 Enum 으로 막지만, 읽기까지 막으면
    DB에 남아있는 옛 데이터 하나 때문에 목록 전체가 500이 된다.

    실제로 예전 값을 DB에 직접 넣어보고 목록이 살아있는지 확인한다.
    """
    make_asset(asset_no="OK-1", asset_type="LAPTOP")

    from app.db.database import SessionLocal
    from app.models.asset import Asset

    db = SessionLocal()
    db.add(Asset(asset_no="LEGACY-1", asset_type="PC", status="IN_USE"))
    db.commit()
    db.close()

    res = admin.get("/assets/")
    assert res.status_code == 200
    body = res.json()
    items = body["items"] if isinstance(body, dict) else body
    types = {i["asset_type"] for i in items}
    assert "PC" in types  # 옛 값도 그대로 보여준다
    assert "LAPTOP" in types


def test_자산을_수정한다(admin, make_asset):
    asset = make_asset()
    res = admin.put(f"/assets/{asset['id']}", json={"status": "REPAIR"})
    assert res.status_code == 200
    assert admin.get(f"/assets/{asset['id']}").json()["status"] == "REPAIR"


def test_없는_자산을_조회하면_404(admin):
    res = admin.get("/assets/00000000-0000-0000-0000-000000000000")
    assert res.status_code == 404


# ---- 값 정리 (제조사·모델·CPU·운영체제 표기 통일) ----

def test_값_목록은_쓰는_대수와_함께_많이_쓰는_순으로(admin, make_asset):
    make_asset(asset_no="A1", os="Windows 11 Pro")
    make_asset(asset_no="A2", os="Windows 11 Pro")
    make_asset(asset_no="A3", os="Windows11")
    make_asset(asset_no="A4")  # os 없음 — 목록에 안 나와야 한다

    rows = admin.get("/assets/spec-values?field=os").json()

    assert rows == [
        {"value": "Windows 11 Pro", "count": 2},
        {"value": "Windows11", "count": 1},
    ]


def test_값을_다른_값으로_합친다(admin, make_asset):
    make_asset(asset_no="A1", os="Windows11")
    make_asset(asset_no="A2", os="Windows11")
    make_asset(asset_no="A3", os="Windows 11 Pro")

    res = admin.post("/assets/spec-values/replace", json={
        "field": "os", "from_value": "Windows11", "to_value": "Windows 11 Pro",
    })

    assert res.status_code == 200
    assert res.json()["changed"] == 2
    assert admin.get("/assets/spec-values?field=os").json() == [
        {"value": "Windows 11 Pro", "count": 3},
    ]


def test_바꿀_값을_비우면_값이_지워진다(admin, make_asset):
    make_asset(asset_no="A1", os="쓸모없는값")

    res = admin.post("/assets/spec-values/replace", json={
        "field": "os", "from_value": "쓸모없는값", "to_value": "",
    })

    assert res.json()["changed"] == 1
    assert admin.get("/assets/spec-values?field=os").json() == []


def test_숫자_항목은_정리_대상이_아니다(admin):
    res = admin.get("/assets/spec-values?field=memory_gb")

    assert res.status_code == 400


def test_원본과_바꿀_값이_같으면_거부한다(admin, make_asset):
    make_asset(asset_no="A1", cpu="i7")

    res = admin.post("/assets/spec-values/replace", json={
        "field": "cpu", "from_value": "i7", "to_value": "i7",
    })

    assert res.status_code == 400


def test_값_정리_경로가_자산_상세보다_먼저_잡힌다(admin):
    """/assets/{asset_id} 보다 뒤에 선언하면 'spec-values' 를 UUID 로 읽어 422 가 난다."""
    res = admin.get("/assets/spec-values?field=os")

    assert res.status_code == 200


def test_새로_등록한_자산은_보관이다(admin):
    """사용 중으로 두면 '사용자 없는 사용 중' 자산이 되어,
    지급하려고 보관 목록을 열어도 거기 없다 — 등록해놓고 못 찾게 된다."""
    res = admin.post("/assets/", json={"asset_no": "NB-9001", "asset_type": "LAPTOP"})

    assert res.status_code == 200, res.text
    assert res.json()["status"] == "STORAGE"


def test_등록할_때_상태를_지정하면_그대로_따른다(admin):
    res = admin.post("/assets/", json={
        "asset_no": "NB-9002", "asset_type": "LAPTOP", "status": "REPAIR"})

    assert res.json()["status"] == "REPAIR"


def test_새_자산은_지급_목록에_바로_나온다(admin, make_employee):
    """직원 모달의 '보관 자산 선택' 은 STORAGE 만 보여준다."""
    admin.post("/assets/", json={"asset_no": "NB-9003", "asset_type": "LAPTOP"})

    storage = [a for a in admin.get("/assets/").json() if a["status"] == "STORAGE"]

    assert "NB-9003" in [a["asset_no"] for a in storage]
