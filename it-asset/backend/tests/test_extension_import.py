"""내선번호 자료 올리기.

화면에서 엑셀·CSV 를 올려 한꺼번에 넣는 길이다. 남의 자료를 한 방에
갈아엎는 일이 없도록 '미리보기 먼저, 넣기는 따로' 로 되어 있는지를 본다.
"""

import csv
import io
import zipfile

import pytest

NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'


def csv_bytes(rows, encoding="cp949"):
    """엑셀에서 저장한 CSV 는 대개 cp949 다. 그 상태 그대로 만든다."""
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    return buffer.getvalue().encode(encoding)


def xlsx_bytes(rows):
    """openpyxl 없이 최소한의 xlsx 를 만든다 (읽는 쪽도 표준 라이브러리만 쓴다)."""
    strings, index = [], {}

    def sid(text):
        if text not in index:
            index[text] = len(strings)
            strings.append(text)
        return index[text]

    body = ""
    for r, row in enumerate(rows, start=1):
        cells = ""
        for c, text in enumerate(row):
            if text == "":
                continue
            ref = f"{chr(ord('A') + c)}{r}"
            cells += f'<c r="{ref}" t="s"><v>{sid(str(text))}</v></c>'
        body += f'<row r="{r}">{cells}</row>'

    si = "".join(f"<si><t>{s}</t></si>" for s in strings)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as book:
        book.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        book.writestr("xl/sharedStrings.xml", f'<?xml version="1.0"?><sst {NS}>{si}</sst>')
        book.writestr("xl/worksheets/sheet1.xml",
                      f'<?xml version="1.0"?><worksheet {NS}><sheetData>{body}</sheetData></worksheet>')
    return buffer.getvalue()


def upload(admin, data, filename="내선.csv", **form):
    return admin.post(
        "/extensions/import",
        files={"file": (filename, data, "application/octet-stream")},
        data={k: str(v).lower() for k, v in form.items()},
    )


@pytest.fixture
def people(make_employee):
    return [
        make_employee(emp_no="E001", name="정예호", department="생산관리팀"),
        make_employee(emp_no="E002", name="한윤현", department="경영지원팀"),
    ]


# ---- 미리보기 ----

def test_미리보기는_아무것도_바꾸지_않는다(admin, people):
    data = csv_bytes([["내선번호", "이름"], ["1234", "정예호"]])

    res = upload(admin, data)

    assert res.status_code == 200, res.text
    assert res.json()["applied"] is False
    assert len(res.json()["new"]) == 1
    # 실제로는 안 들어갔어야 한다
    assert admin.get("/extensions/").json() == []


def test_넣기를_켜야_들어간다(admin, people):
    data = csv_bytes([["내선번호", "이름"], ["1234", "정예호"]])

    res = upload(admin, data, apply=True)

    assert res.json()["applied"] is True
    assert res.json()["added"] == 1
    rows = admin.get("/extensions/").json()
    assert rows[0]["number"] == "1234"
    assert rows[0]["employee_name"] == "정예호"


def test_엑셀도_읽는다(admin, people):
    data = xlsx_bytes([["내선번호", "이름", "IP"], ["1234", "한윤현", "10.10.100.5"]])

    res = upload(admin, data, filename="내선.xlsx", apply=True)

    assert res.status_code == 200, res.text
    row = admin.get("/extensions/").json()[0]
    assert row["number"] == "1234"
    assert row["employee_name"] == "한윤현"
    assert row["ip_address"] == "10.10.100.5"


def test_전화기_IP_도_같이_들어간다(admin, people):
    data = csv_bytes([["내선번호", "이름", "IP"], ["1234", "정예호", "10.10.100.11"]])

    upload(admin, data, apply=True)

    phones = admin.get("/ip-assignments?kind=PHONE").json()
    assert [r["ip_address"] for r in phones] == ["10.10.100.11"]
    assert phones[0]["employee_name"] == "정예호"


# ---- 건너뛰는 줄과 그 이유 ----

def test_없는_사람은_이유와_함께_건너뛴다(admin, people):
    data = csv_bytes([["내선번호", "이름"], ["1234", "없는사람"], ["1235", "정예호"]])

    body = upload(admin, data, apply=True).json()

    assert body["added"] == 1
    assert any("없는사람" in line and "2줄" in line for line in body["skipped"])


def test_동명이인은_건너뛰고_사번을_요구한다(admin, make_employee):
    """엉뚱한 사람에게 번호를 붙이느니 손으로 고치는 게 낫다."""
    make_employee(emp_no="E001", name="정예호", department="생산관리팀")
    make_employee(emp_no="E002", name="정예호", department="영업팀")
    data = csv_bytes([["내선번호", "이름"], ["1234", "정예호"]])

    body = upload(admin, data, apply=True).json()

    assert body["added"] == 0
    assert any("2명" in line and "사번" in line for line in body["skipped"])


def test_사번이_있으면_동명이인도_정확히_찾는다(admin, make_employee):
    make_employee(emp_no="E001", name="정예호", department="생산관리팀")
    make_employee(emp_no="E002", name="정예호", department="영업팀")
    data = csv_bytes([["내선번호", "이름", "사번"], ["1234", "정예호", "E002"]])

    upload(admin, data, apply=True)

    assert admin.get("/extensions/").json()[0]["employee_department"] == "영업팀"


def test_파일_안에서_번호가_겹치면_건너뛴다(admin, people):
    data = csv_bytes([["내선번호", "이름"], ["1234", "정예호"], ["1234", "한윤현"]])

    body = upload(admin, data, apply=True).json()

    assert body["added"] == 1
    assert any("두 번" in line for line in body["skipped"])


def test_이미_쓰이는_IP_면_번호만_넣는다(admin, people, make_asset):
    """IP 하나 때문에 그 사람 번호까지 통째로 빠지면 곤란하다."""
    asset = make_asset()
    admin.post("/ip-assignments", json={"asset_id": asset["id"], "ip_address": "10.10.100.11"})
    data = csv_bytes([["내선번호", "이름", "IP"], ["1234", "정예호", "10.10.100.11"]])

    body = upload(admin, data, apply=True).json()

    assert body["added"] == 1
    assert admin.get("/extensions/").json()[0]["ip_address"] is None
    assert any("이미 쓰이는 주소" in line for line in body["skipped"])


def test_이미_있는_번호는_기본으로_건너뛴다(admin, people):
    admin.post("/extensions/", json={"number": "1234", "zone": "3층"})
    data = csv_bytes([["내선번호", "이름", "구역"], ["1234", "정예호", "4층"]])

    body = upload(admin, data, apply=True).json()

    assert body["added"] == 0
    assert admin.get("/extensions/").json()[0]["zone"] == "3층"


def test_덮어쓰기를_켜면_고친다(admin, people):
    admin.post("/extensions/", json={"number": "1234", "zone": "3층"})
    data = csv_bytes([["내선번호", "이름", "구역"], ["1234", "정예호", "4층"]])

    body = upload(admin, data, apply=True, overwrite=True).json()

    assert body["updated"] == 1
    row = admin.get("/extensions/").json()[0]
    assert row["zone"] == "4층"
    assert row["employee_name"] == "정예호"


def test_한_사람이_이미_번호를_쓰면_건너뛴다(admin, people):
    first = admin.post("/extensions/", json={"number": "1111"}).json()
    admin.put(f"/extensions/{first['id']}/employee", json={"employee_id": people[0]["id"]})
    data = csv_bytes([["내선번호", "이름"], ["1234", "정예호"]])

    body = upload(admin, data, apply=True).json()

    assert body["added"] == 0
    assert any("1111" in line for line in body["skipped"])


# ---- 잘못된 파일 ----

def test_머리글이_없으면_무엇이_필요한지_알려준다(admin):
    data = csv_bytes([["1234", "정예호"]])

    res = upload(admin, data)

    assert res.status_code == 400
    assert "내선번호" in res.json()["detail"]


def test_빈_파일은_거절한다(admin):
    assert upload(admin, b"").status_code == 400


def test_엑셀이_아닌_것을_xlsx_로_올리면_알려준다(admin):
    res = upload(admin, "이건 엑셀이 아닙니다".encode(), filename="가짜.xlsx")

    assert res.status_code == 400
    assert "엑셀" in res.json()["detail"]


def test_관리자가_아니면_올릴_수_없다(client):
    res = client.post("/extensions/import",
                      files={"file": ("a.csv", b"x", "text/csv")})

    assert res.status_code == 401


def test_넣기_경로가_내선_상세보다_먼저_잡힌다(admin):
    """/extensions/{id} 가 먼저면 'import' 를 id 로 읽어서 422 가 난다."""
    res = upload(admin, csv_bytes([["내선번호"], ["1234"]]))

    assert res.status_code == 200


def test_한글_파일이름도_읽는다(admin, people):
    """실제로 올리는 파일은 '내선번호.xlsx' 처럼 한글 이름이다."""
    data = xlsx_bytes([["내선번호", "이름"], ["1234", "정예호"]])

    res = upload(admin, data, filename="내선번호 자료.xlsx", apply=True)

    assert res.status_code == 200, res.text
    assert res.json()["added"] == 1
