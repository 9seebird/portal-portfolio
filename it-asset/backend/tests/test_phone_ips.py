"""전화기 IP.

IP 를 두 종류로 나눴다.
  NETWORK : PC·서버 등 자산에 붙는 IP (원래 있던 것)
  PHONE   : 전화기에 붙는 IP. 전화기는 자산으로 등록하지 않으므로
            내선번호를 전화기의 신원으로 삼는다.

종류와 붙는 대상이 어긋나면 어느 화면에서도 안 보이는 유령 자료가 되므로
그걸 막는 데 집중한다.
"""

import pytest


@pytest.fixture
def extension(admin):
    return admin.post("/extensions/", json={"number": "1234"}).json()


def phone_ip(admin, extension_id, ip="10.10.100.5", **kw):
    return admin.post("/ip-assignments", json={
        "kind": "PHONE", "extension_id": extension_id, "ip_address": ip, **kw,
    })


# ---- 종류에 맞는 대상 ----

def test_전화기_IP_는_내선에_붙는다(admin, extension):
    res = phone_ip(admin, extension["id"])

    assert res.status_code == 200, res.text
    assert res.json()["kind"] == "PHONE"
    assert res.json()["extension_number"] == "1234"


def test_전화기_IP_에_내선이_없으면_거절한다(admin):
    res = admin.post("/ip-assignments", json={"kind": "PHONE", "ip_address": "10.10.100.5"})

    assert res.status_code == 400
    assert "내선" in res.json()["detail"]


def test_네트워크_IP_에_자산이_없으면_거절한다(admin):
    res = admin.post("/ip-assignments", json={"kind": "NETWORK", "ip_address": "10.20.30.50"})

    assert res.status_code == 400
    assert "자산" in res.json()["detail"]


def test_모르는_종류는_거절한다(admin, make_asset):
    asset = make_asset()
    res = admin.post("/ip-assignments", json={
        "kind": "WIFI", "asset_id": asset["id"], "ip_address": "10.20.30.50"})

    assert res.status_code == 400


def test_기존_네트워크_IP_는_그대로_동작한다(admin, make_asset):
    """종류를 안 주면 NETWORK 다. 이미 있던 화면·스크립트가 깨지면 안 된다."""
    asset = make_asset()

    res = admin.post("/ip-assignments", json={
        "asset_id": asset["id"], "ip_address": "10.20.30.50"})

    assert res.status_code == 200, res.text
    assert res.json()["kind"] == "NETWORK"
    assert res.json()["asset_no"] == asset["asset_no"]


# ---- 한 내선에 IP 하나 ----

def test_한_내선에_전화기_IP_는_하나만(admin, extension):
    phone_ip(admin, extension["id"], "10.10.100.5")

    res = phone_ip(admin, extension["id"], "10.10.100.6")

    assert res.status_code == 409
    assert "10.10.100.5" in res.json()["detail"]


def test_같은_IP_를_두_곳에_못_준다(admin, make_asset, extension):
    asset = make_asset()
    admin.post("/ip-assignments", json={"asset_id": asset["id"], "ip_address": "10.10.100.5"})

    res = phone_ip(admin, extension["id"], "10.10.100.5")

    assert res.status_code == 409


# ---- 걸러 보기 ----

def test_종류로_걸러서_본다(admin, make_asset, extension):
    asset = make_asset()
    admin.post("/ip-assignments", json={"asset_id": asset["id"], "ip_address": "10.20.30.50"})
    phone_ip(admin, extension["id"], "10.10.100.5")

    network = admin.get("/ip-assignments?kind=NETWORK").json()
    phones = admin.get("/ip-assignments?kind=PHONE").json()

    assert [r["ip_address"] for r in network] == ["10.20.30.50"]
    assert [r["ip_address"] for r in phones] == ["10.10.100.5"]
    assert len(admin.get("/ip-assignments").json()) == 2


def test_전화기_IP_목록에_쓰는_사람_이름이_같이_나온다(admin, make_employee, extension):
    emp = make_employee(name="정예호", department="생산관리팀")
    admin.put(f"/extensions/{extension['id']}/employee", json={"employee_id": emp["id"]})
    phone_ip(admin, extension["id"])

    row = admin.get("/ip-assignments?kind=PHONE").json()[0]

    assert row["employee_name"] == "정예호"
    assert row["employee_department"] == "생산관리팀"


# ---- 빈 IP ----

def test_빈_IP_를_종류별로_뽑는다(admin):
    admin.post("/ip-ranges", json={
        "name": "전화기", "start_ip": "10.10.100.1", "end_ip": "10.10.100.5", "kind": "PHONE"})
    admin.post("/ip-ranges", json={
        "name": "3층", "start_ip": "10.20.30.1", "end_ip": "10.20.30.3", "kind": "NETWORK"})

    phones = admin.get("/ip-addresses/free?kind=PHONE").json()

    assert len(phones) == 5
    assert all(row["ip_address"].startswith("10.10.100.") for row in phones)
    assert len(admin.get("/ip-addresses/free").json()) == 8


def test_쓰는_중인_IP_는_빈_목록에서_빠진다(admin, extension):
    admin.post("/ip-ranges", json={
        "name": "전화기", "start_ip": "10.10.100.1", "end_ip": "10.10.100.3", "kind": "PHONE"})
    phone_ip(admin, extension["id"], "10.10.100.2")

    free = [row["ip_address"] for row in admin.get("/ip-addresses/free?kind=PHONE").json()]

    assert free == ["10.10.100.1", "10.10.100.3"]


def test_대역에_오타가_있어도_나머지는_나온다(admin):
    """대역을 손으로 넣다 보면 오타가 난다. 그 하나 때문에 화면 전체가 죽으면 안 된다."""
    admin.post("/ip-ranges", json={
        "name": "오타", "start_ip": "10.10.100.", "end_ip": "10.10.100.9", "kind": "PHONE"})
    admin.post("/ip-ranges", json={
        "name": "정상", "start_ip": "10.10.101.1", "end_ip": "10.10.101.2", "kind": "PHONE"})

    free = admin.get("/ip-addresses/free?kind=PHONE").json()

    assert [row["ip_address"] for row in free] == ["10.10.101.1", "10.10.101.2"]


# ---- 다른 화면에 얹히는지 ----

def test_내선_목록에_전화기_IP_가_같이_나온다(admin, extension):
    phone_ip(admin, extension["id"], "10.10.100.5")

    assert admin.get("/extensions/").json()[0]["ip_address"] == "10.10.100.5"


def test_직원별_현황에_전화기_IP_가_나온다(admin, make_employee, extension):
    emp = make_employee()
    admin.put(f"/extensions/{extension['id']}/employee", json={"employee_id": emp["id"]})
    phone_ip(admin, extension["id"], "10.10.100.5")

    row = [e for e in admin.get("/employees/workspace").json() if e["id"] == emp["id"]][0]

    assert row["extension"] == "1234"
    assert row["phone_ip"] == "10.10.100.5"


def test_내선을_지우면_붙어_있던_전화기_IP_도_풀린다(admin, extension):
    """안 그러면 어디에도 안 보이는 유령 IP 가 남아 그 주소를 다시 못 쓴다."""
    phone_ip(admin, extension["id"], "10.10.100.5")

    admin.delete(f"/extensions/{extension['id']}")

    assert admin.get("/ip-assignments?kind=PHONE").json() == []


def test_전화기_IP_는_자산_화면에_섞이지_않는다(admin, make_asset, extension):
    """직원별 현황의 자산 칸에 전화기 IP 가 끼면 PC 의 IP 로 오해한다."""
    asset = make_asset()
    emp_ips = admin.post("/ip-assignments", json={
        "asset_id": asset["id"], "ip_address": "10.20.30.50"}).json()
    phone_ip(admin, extension["id"], "10.10.100.5")

    rows = admin.get(f"/ip-assignments?asset_id={asset['id']}").json()

    assert [r["ip_address"] for r in rows] == ["10.20.30.50"]
    assert emp_ips["kind"] == "NETWORK"


# ---- 중복 IP 를 알려주는 방식 ----

def test_중복_IP_는_어디에_쓰이는지_알려준다(admin, make_employee, extension):
    """'이미 할당됨' 만으로는 어느 자리를 찾아가야 할지 알 수 없다."""
    emp = make_employee(name="정예호")
    admin.put(f"/extensions/{extension['id']}/employee", json={"employee_id": emp["id"]})
    phone_ip(admin, extension["id"], "10.10.100.5")
    other = admin.post("/extensions/", json={"number": "5678"}).json()

    res = phone_ip(admin, other["id"], "10.10.100.5")

    assert res.status_code == 409
    detail = res.json()["detail"]
    assert "1234" in detail and "정예호" in detail


def test_자산이_쓰는_IP_면_자산번호를_알려준다(admin, make_asset, extension):
    asset = make_asset(asset_no="NB-1234")
    admin.post("/ip-assignments", json={"asset_id": asset["id"], "ip_address": "10.20.30.50"})

    res = phone_ip(admin, extension["id"], "10.20.30.50")

    assert res.status_code == 409
    assert "NB-1234" in res.json()["detail"]


def test_IP_바꾸기가_막혀도_원래_IP_는_남는다(admin, extension):
    """지우고 다시 만드는 방식이면 여기서 멀쩡하던 IP 까지 날아간다."""
    phone_ip(admin, extension["id"], "10.10.100.5")
    other = admin.post("/extensions/", json={"number": "5678"}).json()
    phone_ip(admin, other["id"], "10.10.100.6")

    row = admin.get(f"/ip-assignments?extension_id={extension['id']}").json()[0]
    res = admin.put(f"/ip-assignments/{row['id']}", json={"ip_address": "10.10.100.6"})

    assert res.status_code == 409
    assert admin.get("/extensions/").json()[0]["ip_address"] == "10.10.100.5"


def test_네트워크_IP_에도_쓰는_사람이_나온다(admin, make_asset, make_employee):
    """자산번호만 보여주면 누구 자리를 찾아가야 할지 알 수 없다."""
    asset = make_asset(asset_no="NB-0007")
    emp = make_employee(name="한주우", department="해외영업팀")
    admin.post("/asset-assignments/", json={"asset_id": asset["id"], "employee_id": emp["id"]})
    admin.post("/ip-assignments", json={"asset_id": asset["id"], "ip_address": "10.20.40.81"})

    row = admin.get("/ip-assignments?kind=NETWORK").json()[0]

    assert row["asset_no"] == "NB-0007"
    assert row["employee_name"] == "한주우"
    assert row["employee_department"] == "해외영업팀"


def test_아무도_안_쓰는_자산의_IP_는_사용자가_비어_있다(admin, make_asset):
    asset = make_asset()
    admin.post("/ip-assignments", json={"asset_id": asset["id"], "ip_address": "10.20.30.50"})

    assert admin.get("/ip-assignments").json()[0]["employee_name"] is None


# ---- 세 화면이 같은 것을 보게 ----
#
# 상태가 FREE 인 채로 내선에 붙어 있으면 IP 관리에는 나오는데
# 내선 관리·직원별 현황에는 안 나왔다. 화면마다 딴소리를 하게 된다.

def test_전화기_IP_는_늘_사용중으로_들어간다(admin, extension):
    res = admin.post("/ip-assignments", json={
        "kind": "PHONE", "extension_id": extension["id"],
        "ip_address": "10.10.100.5", "status": "FREE"})

    assert res.json()["status"] == "USED"


def test_전화기_IP_를_FREE_로_못_바꾼다(admin, extension):
    """안 쓸 거면 지우면 된다. 어중간한 상태를 두면 화면이 갈린다."""
    phone_ip(admin, extension["id"], "10.10.100.5")
    row = admin.get("/ip-assignments?kind=PHONE").json()[0]

    res = admin.put(f"/ip-assignments/{row['id']}", json={"status": "FREE"})

    assert res.json()["status"] == "USED"


def test_상태가_어떻든_세_화면이_같은_값을_본다(admin, make_employee, extension):
    emp = make_employee()
    admin.put(f"/extensions/{extension['id']}/employee", json={"employee_id": emp["id"]})
    phone_ip(admin, extension["id"], "10.10.100.5")
    # 예전 자료처럼 DB 에 FREE 로 남아 있는 경우를 흉내낸다
    from app.db.database import SessionLocal
    from app.models.ip_assignment import IPAssignment
    db = SessionLocal()
    db.query(IPAssignment).update({"status": "FREE"}, synchronize_session=False)
    db.commit()
    db.close()

    ip_screen = admin.get("/ip-assignments?kind=PHONE").json()[0]["ip_address"]
    ext_screen = admin.get("/extensions/").json()[0]["ip_address"]
    workspace = [e for e in admin.get("/employees/workspace").json()
                 if e["id"] == emp["id"]][0]["phone_ip"]

    assert ip_screen == ext_screen == workspace == "10.10.100.5"


def test_한_내선에_두_번째_IP_는_상태와_무관하게_막힌다(admin, extension):
    phone_ip(admin, extension["id"], "10.10.100.5")
    row = admin.get("/ip-assignments?kind=PHONE").json()[0]
    from app.db.database import SessionLocal
    from app.models.ip_assignment import IPAssignment
    db = SessionLocal()
    import uuid as _uuid
    stored = db.query(IPAssignment).filter(
        IPAssignment.id == _uuid.UUID(row["id"])).first()
    stored.status = "FREE"
    db.commit()
    db.close()

    res = phone_ip(admin, extension["id"], "10.10.100.6")

    assert res.status_code == 409
