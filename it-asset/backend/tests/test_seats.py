"""자리 배치.

배치도의 값은 '누가 어디 앉아 있나'다. 그게 틀리면
장비를 찾으러 엉뚱한 자리로 가게 되므로, 사람과 자리가
1:1 로 유지되는지를 집중적으로 확인한다.
"""

import uuid

import pytest

from app.db.database import SessionLocal
from app.models.seat import Seat


def make_seat(floor="3층", row=1, col=1, kind="DESK", label="자리", **kw):
    db = SessionLocal()
    try:
        seat = Seat(id=uuid.uuid4(), floor=floor, row_idx=row, col_idx=col,
                    kind=kind, label=label, **kw)
        db.add(seat)
        db.commit()
        return str(seat.id)
    finally:
        db.close()


@pytest.fixture
def seat(admin):
    return make_seat()


def test_층_목록에_격자_크기와_인원이_나온다(admin, make_employee):
    make_seat(row=1, col=1)
    make_seat(row=3, col=5, row_span=2, col_span=3, kind="ROOM", label="회의실")
    seat_id = make_seat(row=2, col=2)
    emp = make_employee()
    admin.put(f"/seats/{seat_id}/employee", json={"employee_id": emp["id"]})

    floors = admin.get("/seats/floors").json()

    assert len(floors) == 1
    assert floors[0]["floor"] == "3층"
    # 3행 + 2칸 = 4행, 5열 + 3칸 = 7열
    assert floors[0]["rows"] == 4
    assert floors[0]["cols"] == 7
    assert floors[0]["desk_count"] == 2
    assert floors[0]["seated_count"] == 1


def test_자리에_직원을_앉히면_이름과_자산수가_함께_나온다(admin, seat, make_employee, make_asset):
    emp = make_employee()
    asset = make_asset()
    admin.post("/asset-assignments/", json={"asset_id": asset["id"], "employee_id": emp["id"]})

    res = admin.put(f"/seats/{seat}/employee", json={"employee_id": emp["id"]})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["employee_name"] == emp["name"]
    assert body["asset_count"] == 1


def test_한_사람을_두_자리에_앉힐_수_없다(admin, make_employee):
    first = make_seat(row=1, col=1)
    second = make_seat(row=1, col=2)
    emp = make_employee()
    admin.put(f"/seats/{first}/employee", json={"employee_id": emp["id"]})

    res = admin.put(f"/seats/{second}/employee", json={"employee_id": emp["id"]})

    assert res.status_code == 409
    # 어느 자리에 이미 있는지 알려줘야 사용자가 조치할 수 있다
    assert "3층" in res.json()["detail"]


def test_자리를_비우면_다른_자리에_앉힐_수_있다(admin, make_employee):
    first = make_seat(row=1, col=1)
    second = make_seat(row=1, col=2)
    emp = make_employee()
    admin.put(f"/seats/{first}/employee", json={"employee_id": emp["id"]})

    admin.put(f"/seats/{first}/employee", json={"employee_id": None})
    res = admin.put(f"/seats/{second}/employee", json={"employee_id": emp["id"]})

    assert res.status_code == 200
    assert res.json()["employee_name"] == emp["name"]


def test_퇴사자는_자리에_앉힐_수_없다(admin, seat, make_employee):
    emp = make_employee()
    admin.post(f"/employees/{emp['id']}/offboard")

    res = admin.put(f"/seats/{seat}/employee", json={"employee_id": emp["id"]})

    assert res.status_code == 400
    assert "퇴사" in res.json()["detail"]


def test_공간에는_사람을_앉힐_수_없다(admin, make_employee):
    room = make_seat(kind="ROOM", label="회의실")
    emp = make_employee()

    res = admin.put(f"/seats/{room}/employee", json={"employee_id": emp["id"]})

    assert res.status_code == 400


def test_자리를_공간으로_바꾸면_앉아있던_사람이_빠진다(admin, seat, make_employee):
    emp = make_employee()
    admin.put(f"/seats/{seat}/employee", json={"employee_id": emp["id"]})

    res = admin.patch(f"/seats/{seat}", json={"kind": "ROOM", "label": "창고"})

    assert res.status_code == 200
    assert res.json()["employee_id"] is None
    assert res.json()["label"] == "창고"


def test_층으로_걸러서_가져온다(admin):
    make_seat(floor="3층", row=1, col=1)
    make_seat(floor="4층", row=1, col=1)

    assert len(admin.get("/seats/?floor=3층").json()) == 1
    assert len(admin.get("/seats/").json()) == 2


def test_로그인_없이는_자리를_바꿀_수_없다(client):
    # 주의: seat 픽스처는 admin 을 거치는데, admin 은 client 에 인증 헤더를 붙인다.
    # 같은 객체라 여기서 seat 픽스처를 쓰면 이미 로그인된 상태가 되어 버린다.
    # 그래서 자리는 DB 에 직접 넣는다.
    seat_id = make_seat()

    res = client.put(f"/seats/{seat_id}/employee", json={"employee_id": None})

    assert res.status_code == 401


def test_배치도_조회는_자리수와_무관하게_쿼리가_일정하다(
    admin, make_employee, make_asset, query_counter
):
    """자리마다 직원을 따로 조회하면(N+1) 자리 수만큼 쿼리가 늘어난다.

    라이선스 화면에서 이미 한 번 겪은 문제(256 → 2)라 여기서는 미리 막아둔다.
    """
    for i in range(20):
        seat_id = make_seat(row=i + 1, col=1)
        emp = make_employee(emp_no=f"E{i:03d}", name=f"직원{i}")
        asset = make_asset(asset_no=f"NB-{i:04d}")
        admin.post("/asset-assignments/", json={"asset_id": asset["id"], "employee_id": emp["id"]})
        admin.put(f"/seats/{seat_id}/employee", json={"employee_id": emp["id"]})

    query_counter["n"] = 0
    res = admin.get("/seats/")

    assert res.status_code == 200
    assert len(res.json()) == 20
    # 자리 조인 1 + 자산 집계 1 + 인증 1~2. 자리 수에 비례하면 안 된다.
    assert query_counter["n"] <= 5, (
        f"자리 20개에 쿼리 {query_counter['n']}개 — N+1 이 생겼습니다."
    )


# ---- 직책자 표시 ----
#
# 엑셀 배치도의 (●) 는 손으로 찍은 것이라 빠지거나 잘못 찍힌 곳이 있었다.
# 직책은 어차피 직원 명단에 있으므로 그걸 보고 판단한다.

def test_직책이_팀장이면_직책자로_표시된다(admin, seat, make_employee):
    emp = make_employee(position="팀장")

    res = admin.put(f"/seats/{seat}/employee", json={"employee_id": emp["id"]})

    assert res.json()["is_manager"] is True
    assert res.json()["employee_position"] == "팀장"


def test_직책에_팀장이_섞여_있어도_잡는다(admin, seat, make_employee):
    emp = make_employee(position="영업1팀장")

    res = admin.put(f"/seats/{seat}/employee", json={"employee_id": emp["id"]})

    assert res.json()["is_manager"] is True


def test_직급이_이사여도_직책자다(admin, seat, make_employee):
    emp = make_employee(rank="이사")

    res = admin.put(f"/seats/{seat}/employee", json={"employee_id": emp["id"]})

    assert res.json()["is_manager"] is True


def test_일반_직원은_직책자가_아니다(admin, seat, make_employee):
    emp = make_employee(position="팀원", rank="대리")

    res = admin.put(f"/seats/{seat}/employee", json={"employee_id": emp["id"]})

    assert res.json()["is_manager"] is False


def test_직책이_비어_있으면_직책자가_아니다(admin, seat, make_employee):
    emp = make_employee()

    res = admin.put(f"/seats/{seat}/employee", json={"employee_id": emp["id"]})

    assert res.json()["is_manager"] is False


def test_엑셀의_동그라미는_표시에_쓰이지_않는다(admin, make_employee):
    """seats.marked 는 엑셀에 뭐가 적혀 있었는지 기록만 하고, 화면 표시는 직책으로 한다."""
    seat_id = make_seat(marked=True)
    emp = make_employee(position="팀원")

    res = admin.put(f"/seats/{seat_id}/employee", json={"employee_id": emp["id"]})

    assert res.json()["marked"] is True        # 엑셀 기록은 남아 있고
    assert res.json()["is_manager"] is False   # 표시는 직책을 따른다


def test_빈_칸을_지울_수_있다(admin):
    seat_id = make_seat()

    res = admin.delete(f"/seats/{seat_id}")

    assert res.status_code == 200
    assert admin.get("/seats/").json() == []


def test_사람이_앉은_자리는_지울_수_없다(admin, seat, make_employee):
    emp = make_employee()
    admin.put(f"/seats/{seat}/employee", json={"employee_id": emp["id"]})

    res = admin.delete(f"/seats/{seat}")

    assert res.status_code == 409
    assert len(admin.get("/seats/").json()) == 1


# ---- 배치 편집 (칸 옮기기 · 새로 만들기) ----

def test_빈_격자에_새_자리를_만든다(admin):
    res = admin.post("/seats/", json={"floor": "3층", "row_idx": 5, "col_idx": 5})

    assert res.status_code == 200, res.text
    assert res.json()["kind"] == "DESK"
    assert len(admin.get("/seats/").json()) == 1


def test_이미_있는_칸_자리에는_못_만든다(admin):
    make_seat(row=2, col=2)

    res = admin.post("/seats/", json={"floor": "3층", "row_idx": 2, "col_idx": 2})

    assert res.status_code == 409


def test_병합된_칸_위에도_못_만든다(admin):
    """회의실처럼 3x3 을 차지하는 칸의 '가운데'도 이미 찬 자리다."""
    make_seat(row=2, col=2, row_span=3, col_span=3, kind="ROOM", label="회의실")

    res = admin.post("/seats/", json={"floor": "3층", "row_idx": 3, "col_idx": 4})

    assert res.status_code == 409


def test_다른_층_같은_좌표는_괜찮다(admin):
    make_seat(floor="3층", row=2, col=2)

    res = admin.post("/seats/", json={"floor": "4층", "row_idx": 2, "col_idx": 2})

    assert res.status_code == 200


def test_칸을_빈_자리로_옮긴다(admin, seat):
    res = admin.patch(f"/seats/{seat}", json={"row_idx": 7, "col_idx": 9})

    assert res.status_code == 200
    assert (res.json()["row_idx"], res.json()["col_idx"]) == (7, 9)


def test_옮긴_뒤에도_앉은_사람은_그대로(admin, seat, make_employee):
    emp = make_employee()
    admin.put(f"/seats/{seat}/employee", json={"employee_id": emp["id"]})

    res = admin.patch(f"/seats/{seat}", json={"row_idx": 4, "col_idx": 4})

    assert res.json()["employee_name"] == emp["name"]


def test_다른_칸_위로는_못_옮긴다(admin):
    first = make_seat(row=1, col=1)
    make_seat(row=1, col=2)

    res = admin.patch(f"/seats/{first}", json={"col_idx": 2})

    assert res.status_code == 409
    assert "이미" in res.json()["detail"]


def test_제자리_이동은_막지_않는다(admin, seat):
    """자기 자신과 겹친다고 판단하면 크기만 바꾸는 것도 못 하게 된다."""
    res = admin.patch(f"/seats/{seat}", json={"row_idx": 1, "col_idx": 1, "col_span": 2})

    assert res.status_code == 200
    assert res.json()["col_span"] == 2


def test_좌표는_1부터(admin, seat):
    res = admin.patch(f"/seats/{seat}", json={"row_idx": 0})

    assert res.status_code == 400
