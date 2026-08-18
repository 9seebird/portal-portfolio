"""내선번호 자료 읽고 넣기.

화면(파일 올리기)과 명령줄 스크립트가 같은 규칙을 쓰도록 여기 모아둔다.
둘이 따로 놀면 "스크립트로는 되는데 화면에서는 안 되네" 같은 일이 생긴다.

바깥에서 쓰는 것은 셋뿐이다.
    read_table(data, filename) -> 줄 목록
    plan(db, rows, overwrite)  -> 뭐가 들어갈지 (아무것도 안 바꾼다)
    apply_plan(db, planned)    -> 실제로 넣는다
"""

import csv
import io
import re
import uuid
import zipfile
from xml.etree import ElementTree

from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.extension import Extension
from app.models.ip_assignment import IPAssignment

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# 칸 이름 후보. 왼쪽이 우리가 쓰는 이름.
HEADERS = {
    "number": ("내선", "내선번호", "내선 번호", "전화", "전화번호", "번호", "ext", "extension"),
    "name": ("이름", "성명", "사용자", "직원", "name"),
    "emp_no": ("사번", "사원번호", "emp_no"),
    "department": ("부서", "소속", "팀", "department"),
    "zone": ("구역", "층", "위치", "zone"),
    "note": ("메모", "비고", "note"),
    "ip": ("ip", "아이피", "전화기ip", "ip주소", "ip address"),
}


class ImportError_(Exception):
    """자료를 아예 읽을 수 없을 때. 화면에는 이 문구가 그대로 나간다."""


# ---------------------------------------------------------------- 파일 읽기

def read_table(data: bytes, filename: str) -> list[list[str]]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        return _read_xlsx(data)
    return _read_csv(data)


def _read_csv(data: bytes) -> list[list[str]]:
    # 엑셀에서 저장한 CSV 는 대개 cp949, 요즘 것은 utf-8-sig
    for encoding in ("utf-8-sig", "cp949", "utf-8"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        return list(csv.reader(io.StringIO(text, newline="")))
    raise ImportError_("CSV 를 읽지 못했습니다. 엑셀에서 'CSV UTF-8' 로 다시 저장해 보세요.")


def _read_xlsx(data: bytes) -> list[list[str]]:
    """xlsx 는 zip 안의 XML 이다. openpyxl 없이 표준 라이브러리만으로 읽는다."""
    try:
        book = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ImportError_("엑셀 파일을 열지 못했습니다. 파일이 손상됐거나 형식이 다릅니다.")

    with book:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in book.namelist():
            tree = ElementTree.fromstring(book.read("xl/sharedStrings.xml"))
            for item in tree.findall(f"{NS}si"):
                shared.append("".join(t.text or "" for t in item.iter(f"{NS}t")))

        names = [n for n in book.namelist() if n.startswith("xl/worksheets/sheet")]
        if not names:
            raise ImportError_("시트를 찾지 못했습니다.")
        sheet = ElementTree.fromstring(book.read(sorted(names)[0]))

        rows = []
        for row in sheet.iter(f"{NS}row"):
            cells: dict[int, str] = {}
            for cell in row.findall(f"{NS}c"):
                col = _column_index(cell.get("r", ""))
                value_el = cell.find(f"{NS}v")
                text = value_el.text if value_el is not None else None
                if cell.get("t") == "s" and text is not None:
                    text = shared[int(text)]
                elif cell.get("t") == "inlineStr":
                    text = "".join(t.text or "" for t in cell.iter(f"{NS}t"))
                cells[col] = (text or "").strip()
            if cells:
                rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
        return rows


def _column_index(ref: str) -> int:
    """'B3' -> 1. 빈 칸은 XML 에 아예 없으므로 좌표로 자리를 맞춰야 한다."""
    letters = re.match(r"[A-Z]+", ref)
    if not letters:
        return 0
    index = 0
    for ch in letters.group():
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index - 1


def map_headers(header_row: list[str]) -> dict:
    """첫 줄을 보고 어느 칸이 무엇인지 정한다."""
    found = {}
    for position, raw in enumerate(header_row):
        label = str(raw or "").strip().lower().replace(" ", "")
        for key, candidates in HEADERS.items():
            if key in found:
                continue
            if any(label == c.lower().replace(" ", "") for c in candidates):
                found[key] = position
    return found


# ---------------------------------------------------------------- 계획 세우기

def plan(db: Session, rows: list[list[str]], overwrite: bool = False) -> dict:
    """뭐가 들어갈지만 계산한다. DB 는 읽기만 한다.

    건너뛴 줄은 이유를 함께 돌려준다 — 그냥 '몇 개 실패' 라고만 하면
    엑셀의 어느 줄을 고쳐야 할지 알 수 없다.
    """
    rows = [row for row in rows if any(str(cell).strip() for cell in row)]
    if not rows:
        raise ImportError_("파일이 비어 있습니다.")

    columns = map_headers(rows[0])
    if "number" not in columns:
        raise ImportError_(
            "'내선번호' 칸을 못 찾았습니다. 첫 줄에 칸 이름이 있어야 합니다. "
            f"쓸 수 있는 이름: {', '.join(HEADERS['number'])}"
        )

    def value(row, key):
        index = columns.get(key)
        if index is None or index >= len(row):
            return ""
        return str(row[index] or "").strip()

    employees = db.query(Employee).filter(Employee.status == "ACTIVE").all()
    by_emp_no = {e.emp_no: e for e in employees if e.emp_no}
    by_name: dict[str, list[Employee]] = {}
    for employee in employees:
        by_name.setdefault(employee.name.strip(), []).append(employee)

    existing = {e.number: e for e in db.query(Extension).all()}
    number_by_employee = {e.employee_id: e.number for e in existing.values() if e.employee_id}
    used_ips = {
        row.ip_address for row in db.query(IPAssignment).filter(
            IPAssignment.status != "FREE"
        ).all()
    }

    new, update, skipped = [], [], []
    seen_numbers, seen_ips = set(), set()

    for line_no, row in enumerate(rows[1:], start=2):
        number = value(row, "number")
        if not number:
            continue
        if number in seen_numbers:
            skipped.append(f"{line_no}줄: 파일 안에 {number} 가 두 번 나옵니다")
            continue
        seen_numbers.add(number)

        name = value(row, "name")
        emp_no = value(row, "emp_no")

        employee = None
        if emp_no and emp_no in by_emp_no:
            employee = by_emp_no[emp_no]
        elif name:
            matches = by_name.get(name, [])
            if len(matches) == 1:
                employee = matches[0]
            elif len(matches) > 1:
                # 동명이인. 사번 없이는 누구인지 알 수 없다.
                skipped.append(f"{line_no}줄: '{name}' 이 {len(matches)}명입니다 (사번 칸을 넣어 주세요)")
                continue
            else:
                skipped.append(f"{line_no}줄: '{name}' 을 재직자 명단에서 못 찾았습니다")
                continue

        if employee and employee.id in number_by_employee:
            current = number_by_employee[employee.id]
            if current != number:
                skipped.append(f"{line_no}줄: {employee.name} 님은 이미 내선 {current} 를 씁니다")
                continue

        ip = value(row, "ip")
        if ip and (ip in used_ips or ip in seen_ips):
            skipped.append(f"{line_no}줄: {ip} 는 이미 쓰이는 주소라 번호만 넣습니다")
            ip = None
        if ip:
            seen_ips.add(ip)

        item = {
            "line": line_no,
            "number": number,
            "employee_id": str(employee.id) if employee else None,
            "employee_name": employee.name if employee else None,
            "zone": value(row, "zone") or None,
            "note": value(row, "note") or None,
            "ip": ip or None,
        }

        if number in existing:
            if overwrite:
                update.append(item)
            else:
                skipped.append(f"{line_no}줄: {number} 는 이미 등록돼 있습니다 (덮어쓰기를 켜세요)")
        else:
            new.append(item)
            if employee:
                number_by_employee[employee.id] = number

    return {
        "columns": sorted(columns),
        "new": new,
        "update": update,
        "skipped": skipped,
    }


# ---------------------------------------------------------------- 실제로 넣기

def apply_plan(db: Session, planned: dict) -> dict:
    """plan() 이 만든 계획을 그대로 넣는다. 계획에 없는 일은 하지 않는다."""
    existing = {e.number: e for e in db.query(Extension).all()}

    for item in planned["new"]:
        extension = Extension(
            id=uuid.uuid4(),
            number=item["number"],
            employee_id=uuid.UUID(item["employee_id"]) if item["employee_id"] else None,
            zone=item["zone"],
            note=item["note"],
        )
        db.add(extension)
        _attach_ip(db, extension.id, item["ip"])

    for item in planned["update"]:
        extension = existing.get(item["number"])
        if not extension:
            continue
        extension.employee_id = uuid.UUID(item["employee_id"]) if item["employee_id"] else None
        if item["zone"]:
            extension.zone = item["zone"]
        if item["note"]:
            extension.note = item["note"]
        if item["ip"]:
            # 덮어쓸 때는 그 내선에 붙어 있던 IP 를 먼저 떼어낸다.
            # 안 그러면 한 내선에 IP 가 둘이 된다.
            db.query(IPAssignment).filter(
                IPAssignment.extension_id == extension.id
            ).delete(synchronize_session=False)
            _attach_ip(db, extension.id, item["ip"])

    db.commit()
    # 주의: 여기서 'skipped' 를 개수로 돌려주면 안 된다. 부르는 쪽에서
    # 이유가 담긴 목록과 합쳐지면서 목록이 숫자로 덮여 버린다.
    return {
        "added": len(planned["new"]),
        "updated": len(planned["update"]),
    }


def _attach_ip(db: Session, extension_id, ip: str | None) -> None:
    if not ip:
        return
    db.add(IPAssignment(
        id=uuid.uuid4(),
        kind="PHONE",
        extension_id=extension_id,
        ip_address=ip,
        status="USED",
    ))
