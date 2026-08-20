"""내선번호.

번호는 사람에게 붙는다 — 자리를 옮겨도 따라간다.
값이 틀리면 엉뚱한 사람한테 전화가 가므로, 번호와 사람이 1:1 로
유지되는지를 집중적으로 확인한다.
"""


def test_번호를_등록하고_목록에_나온다(admin):
    res = admin.post("/extensions/", json={"number": "1234", "zone": "3층"})

    assert res.status_code == 200, res.text
    assert res.json()["number"] == "1234"
    assert admin.get("/extensions/").json()[0]["zone"] == "3층"


def test_같은_번호는_두_번_못_넣는다(admin):
    admin.post("/extensions/", json={"number": "1234"})

    res = admin.post("/extensions/", json={"number": "1234"})

    assert res.status_code == 409
    assert "1234" in res.json()["detail"]


def test_앞뒤_공백은_지우고_받는다(admin):
    """엑셀에서 붙여넣으면 공백이 따라온다. 안 지우면 '1234' 와 '1234 ' 가 딴 번호가 된다."""
    admin.post("/extensions/", json={"number": " 1234 "})

    res = admin.post("/extensions/", json={"number": "1234"})

    assert res.status_code == 409


def test_빈_번호는_거절한다(admin):
    assert admin.post("/extensions/", json={"number": "   "}).status_code == 422


def test_번호에_사람을_붙이면_이름이_같이_나온다(admin, make_employee):
    emp = make_employee(name="정예호", department="생산관리팀")
    ext = admin.post("/extensions/", json={"number": "1234"}).json()

    res = admin.put(f"/extensions/{ext['id']}/employee", json={"employee_id": emp["id"]})

    assert res.status_code == 200, res.text
    assert res.json()["employee_name"] == "정예호"
    assert res.json()["employee_department"] == "생산관리팀"


def test_한_사람이_번호_두_개를_가질_수_없다(admin, make_employee):
    emp = make_employee(name="정예호")
    first = admin.post("/extensions/", json={"number": "1234"}).json()
    second = admin.post("/extensions/", json={"number": "5678"}).json()
    admin.put(f"/extensions/{first['id']}/employee", json={"employee_id": emp["id"]})

    res = admin.put(f"/extensions/{second['id']}/employee", json={"employee_id": emp["id"]})

    assert res.status_code == 409
    # 어느 번호를 이미 쓰는지 알려줘야 조치할 수 있다
    assert "1234" in res.json()["detail"]


def test_번호를_비우면_다른_번호를_줄_수_있다(admin, make_employee):
    emp = make_employee()
    first = admin.post("/extensions/", json={"number": "1234"}).json()
    second = admin.post("/extensions/", json={"number": "5678"}).json()
    admin.put(f"/extensions/{first['id']}/employee", json={"employee_id": emp["id"]})

    admin.put(f"/extensions/{first['id']}/employee", json={"employee_id": None})
    res = admin.put(f"/extensions/{second['id']}/employee", json={"employee_id": emp["id"]})

    assert res.status_code == 200


def test_퇴사자에게는_번호를_줄_수_없다(admin, make_employee):
    emp = make_employee()
    admin.post(f"/employees/{emp['id']}/offboard")
    ext = admin.post("/extensions/", json={"number": "1234"}).json()

    res = admin.put(f"/extensions/{ext['id']}/employee", json={"employee_id": emp["id"]})

    assert res.status_code == 400
    assert "퇴사" in res.json()["detail"]


def test_퇴사_처리하면_번호가_반납된다(admin, make_employee):
    """안 그러면 없는 사람이 번호를 물고 있어서 새 사람에게 못 준다."""
    emp = make_employee()
    ext = admin.post("/extensions/", json={"number": "1234"}).json()
    admin.put(f"/extensions/{ext['id']}/employee", json={"employee_id": emp["id"]})

    res = admin.post(f"/employees/{emp['id']}/offboard")

    assert res.json()["released_extensions"] == 1
    assert admin.get("/extensions/").json()[0]["employee_id"] is None


def test_빈_번호만_따로_볼_수_있다(admin, make_employee):
    emp = make_employee()
    used = admin.post("/extensions/", json={"number": "1234"}).json()
    admin.post("/extensions/", json={"number": "5678"})
    admin.put(f"/extensions/{used['id']}/employee", json={"employee_id": emp["id"]})

    free = admin.get("/extensions/?free_only=true").json()

    assert [row["number"] for row in free] == ["5678"]


def test_번호와_이름_부서로_찾는다(admin, make_employee):
    emp = make_employee(name="정예호", department="생산관리팀")
    ext = admin.post("/extensions/", json={"number": "1234"}).json()
    admin.put(f"/extensions/{ext['id']}/employee", json={"employee_id": emp["id"]})
    admin.post("/extensions/", json={"number": "5678"})

    # 부서 이름 일부로도 찾힌다. 위에서 만든 사람의 부서가 「생산관리팀」이다.
    #
    # ★ 여기가 한동안 깨져 있었다. 실명이 섞여 있던 것을 가짜 이름으로 바꾸면서
    #   부서를 「구매팀」→「생산관리팀」으로 고쳤는데, **찾는 글자는 그대로**
    #   두었다. 데이터와 기대값이 따로 놀아서 늘 빈 목록이 나왔다.
    assert [r["number"] for r in admin.get("/extensions/?q=생산").json()] == ["1234"]
    assert [r["number"] for r in admin.get("/extensions/?q=567").json()] == ["5678"]


def test_번호는_숫자_순서로_나온다(admin):
    """문자열로 정렬하면 1000 이 900 앞에 온다."""
    for number in ("900", "1000", "120"):
        admin.post("/extensions/", json={"number": number})

    assert [r["number"] for r in admin.get("/extensions/").json()] == ["120", "900", "1000"]


def test_번호를_고칠_수_있다(admin):
    ext = admin.post("/extensions/", json={"number": "1234"}).json()

    res = admin.patch(f"/extensions/{ext['id']}", json={"number": "4321", "note": "오타"})

    assert res.json()["number"] == "4321"
    assert res.json()["note"] == "오타"


def test_이미_있는_번호로는_못_고친다(admin):
    admin.post("/extensions/", json={"number": "1234"})
    other = admin.post("/extensions/", json={"number": "5678"}).json()

    res = admin.patch(f"/extensions/{other['id']}", json={"number": "1234"})

    assert res.status_code == 409


def test_제_번호_그대로_두는_수정은_막지_않는다(admin):
    """자기 자신과 겹친다고 보면 메모만 고치는 것도 못 하게 된다."""
    ext = admin.post("/extensions/", json={"number": "1234"}).json()

    res = admin.patch(f"/extensions/{ext['id']}", json={"number": "1234", "zone": "4층"})

    assert res.status_code == 200
    assert res.json()["zone"] == "4층"


def test_빈_번호는_지울_수_있다(admin):
    ext = admin.post("/extensions/", json={"number": "1234"}).json()

    res = admin.delete(f"/extensions/{ext['id']}")

    assert res.status_code == 200
    assert admin.get("/extensions/").json() == []


def test_쓰는_사람이_있으면_못_지운다(admin, make_employee):
    emp = make_employee()
    ext = admin.post("/extensions/", json={"number": "1234"}).json()
    admin.put(f"/extensions/{ext['id']}/employee", json={"employee_id": emp["id"]})

    res = admin.delete(f"/extensions/{ext['id']}")

    assert res.status_code == 409
    assert len(admin.get("/extensions/").json()) == 1


def test_로그인_없이는_볼_수_없다(client):
    assert client.get("/extensions/").status_code == 401


# ---- 다른 화면에 얹히는지 ----

def test_직원별_현황에_내선번호가_나온다(admin, make_employee):
    emp = make_employee(name="정예호")
    ext = admin.post("/extensions/", json={"number": "1234"}).json()
    admin.put(f"/extensions/{ext['id']}/employee", json={"employee_id": emp["id"]})

    row = [e for e in admin.get("/employees/workspace").json() if e["id"] == emp["id"]][0]

    assert row["extension"] == "1234"


def test_배치도에도_내선번호가_나온다(admin, make_employee, make_seat):
    """자리를 눌렀을 때 전화번호까지 바로 보이게."""
    emp = make_employee()
    seat_id = make_seat()
    admin.put(f"/seats/{seat_id}/employee", json={"employee_id": emp["id"]})
    ext = admin.post("/extensions/", json={"number": "1234"}).json()
    admin.put(f"/extensions/{ext['id']}/employee", json={"employee_id": emp["id"]})

    assert admin.get("/seats/").json()[0]["employee_extension"] == "1234"


def test_배치도_조회는_내선을_붙여도_쿼리가_일정하다(
    admin, make_employee, make_seat, query_counter
):
    """번호마다 따로 조회하면(N+1) 자리 수만큼 쿼리가 늘어난다."""
    for i in range(15):
        seat_id = make_seat(row=i + 1, col=1)
        emp = make_employee(emp_no=f"X{i:03d}", name=f"직원{i}")
        admin.put(f"/seats/{seat_id}/employee", json={"employee_id": emp["id"]})
        ext = admin.post("/extensions/", json={"number": f"{1000 + i}"}).json()
        admin.put(f"/extensions/{ext['id']}/employee", json={"employee_id": emp["id"]})

    query_counter["n"] = 0
    res = admin.get("/seats/")

    assert res.status_code == 200
    assert query_counter["n"] <= 6, (
        f"자리 15개에 쿼리 {query_counter['n']}개 — N+1 이 생겼습니다."
    )
