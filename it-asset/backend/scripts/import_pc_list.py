from __future__ import annotations

import re
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from sqlalchemy.exc import IntegrityError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.datafiles import find_data_file

from app.db.database import SessionLocal
from app.models.asset import Asset
from app.models.asset_assignment import AssetAssignment
from app.models.employee import Employee
from app.models.ip_assignment import IPAssignment
from app.models.rental_contract import RentalContract
from app.models.software_installation import SoftwareInstallation
from app.models.software_product import SoftwareProduct

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"a": MAIN_NS}


def col_index(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref).group(0)
    value = 0
    for ch in letters:
        value = value * 26 + ord(ch) - 64
    return value - 1


def shared_text(si: ET.Element) -> str:
    return "".join(t.text or "" for t in si.iter(f"{{{MAIN_NS}}}t")).strip()


def load_workbook_rows(path: Path) -> dict[str, list[list[str]]]:
    with ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = [shared_text(si) for si in root.findall("a:si", NS)]

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

        sheets = []
        for sheet in workbook.find("a:sheets", NS):
            name = sheet.attrib["name"]
            rel_id = sheet.attrib[f"{{{REL_NS}}}id"]
            sheets.append((name, "xl/" + relmap[rel_id]))

        result = {}
        for name, target in sheets:
            root = ET.fromstring(archive.read(target))
            rows = []
            for row in root.findall(".//a:sheetData/a:row", NS):
                values = []
                for cell in row.findall("a:c", NS):
                    idx = col_index(cell.attrib["r"])
                    while len(values) <= idx:
                        values.append("")
                    value_node = cell.find("a:v", NS)
                    value = "" if value_node is None else value_node.text or ""
                    if cell.attrib.get("t") == "s" and value:
                        value = shared[int(value)]
                    values[idx] = value.strip() if isinstance(value, str) else value
                rows.append(values)
            result[name] = rows
        return result


def value(row: list[str], index: int) -> str:
    return row[index].strip() if index < len(row) and row[index] else ""


def excel_date(raw: str) -> date | None:
    if not raw:
        return None
    try:
        serial = int(float(raw))
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                pass
        return None
    if serial <= 0:
        return None
    return (datetime(1899, 12, 30) + timedelta(days=serial)).date()


def to_int(raw: str) -> int | None:
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def to_decimal(raw: str) -> Decimal | None:
    if not raw:
        return None
    cleaned = raw.replace(",", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def normalize_asset_type(raw: str) -> str:
    if "노트북" in raw:
        return "LAPTOP"
    if "데스크" in raw:
        return "DESKTOP"
    if "모니터" in raw:
        return "MONITOR"
    if "서버" in raw:
        return "SERVER"
    return "OTHER"


def ensure_software_product(db, name: str, vendor: str, license_type: str = "DEVICE") -> SoftwareProduct:
    product = db.query(SoftwareProduct).filter(SoftwareProduct.name == name).first()
    if not product:
        product = SoftwareProduct(name=name, vendor=vendor, license_type=license_type)
        db.add(product)
        db.flush()
    return product


def install_software(db, asset: Asset, product: SoftwareProduct) -> None:
    exists = db.query(SoftwareInstallation).filter(
        SoftwareInstallation.asset_id == asset.id,
        SoftwareInstallation.software_id == product.id,
    ).first()
    if not exists:
        db.add(SoftwareInstallation(asset_id=asset.id, software_id=product.id))


def software_products_from_pc_row(db, row: list[str]) -> list[SoftwareProduct]:
    products = []
    office = value(row, 18)
    kaspersky = value(row, 19)
    hancom = value(row, 23)

    if office and office.upper() != "X":
        name = "Microsoft 365" if office.upper() == "O365" else f"Microsoft Office {office}"
        products.append(ensure_software_product(db, name, "Microsoft", "USER"))
    if kaspersky and kaspersky.upper() != "X":
        products.append(ensure_software_product(db, "Kaspersky Endpoint Security", "Kaspersky"))
    if hancom and hancom.upper() != "X":
        name = "Hancom Office" if hancom.upper() == "O" else f"Hancom Office {hancom}"
        products.append(ensure_software_product(db, name, "Hancom"))

    return products


def assign_ip_from_pc_row(db, asset: Asset, row: list[str]) -> None:
    ip_address = value(row, 25)
    if not ip_address:
        return

    existing = db.query(IPAssignment).filter(IPAssignment.ip_address == ip_address).first()
    if existing and existing.asset_id != asset.id:
        existing.asset_id = asset.id
        existing.status = "USED"
        existing.hostname = existing.hostname or asset.asset_no
        return
    if existing:
        existing.status = "USED"
        existing.hostname = existing.hostname or asset.asset_no
        return

    db.add(
        IPAssignment(
            asset_id=asset.id,
            ip_address=ip_address,
            hostname=asset.asset_no,
            status="USED",
        )
    )


def upsert_employee(db, row: list[str]) -> Employee | None:
    emp_no = value(row, 3)
    name = value(row, 4)
    if not emp_no or not name:
        return None

    employee = db.query(Employee).filter(Employee.emp_no == emp_no).first()
    if not employee:
        employee = Employee(emp_no=emp_no)
        db.add(employee)

    employee.company = value(row, 1) or employee.company
    employee.department = value(row, 2) or employee.department
    employee.name = name
    employee.location = value(row, 5) or employee.location
    employee.position = value(row, 6) or employee.position
    employee.rank = value(row, 7) or employee.rank
    employee.hire_date = excel_date(value(row, 9)) or employee.hire_date
    employee.email = value(row, 12) or employee.email
    employee.phone = value(row, 13) or employee.phone
    employee.status = "ACTIVE"
    return employee


# PC대장 시트에는 사번(4열)·사용자(5열)·팀명(3열)·지역(2열)이 이미 들어있다.
# 별도의 "직원리스트" 시트가 없는 파일에서도 담당자를 살려내기 위해 여기서 직원을 만든다.
def upsert_employee_from_pc_row(db, row: list[str]) -> Employee | None:
    emp_no = value(row, 3)
    name = value(row, 4)
    if not emp_no or not name:
        return None

    employee = db.query(Employee).filter(Employee.emp_no == emp_no).first()
    if not employee:
        employee = Employee(emp_no=emp_no)
        db.add(employee)

    employee.name = name
    employee.location = value(row, 1) or employee.location      # 지역
    employee.department = value(row, 2) or employee.department   # 팀명/사용층
    employee.status = "ACTIVE"
    return employee


def build_asset_no(row: list[str]) -> str:
    rental_asset_no = value(row, 12)
    purchase_asset_no = value(row, 8)
    sequence = value(row, 0)
    emp_no = value(row, 3)
    return rental_asset_no or purchase_asset_no or f"ROW-{emp_no or 'NOEMP'}-{sequence}"


def upsert_pc_asset(db, row: list[str], employees: dict[str, Employee]) -> Asset | None:
    asset_no = build_asset_no(row)
    if not asset_no:
        return None

    employee = employees.get(value(row, 3))
    asset = db.query(Asset).filter(Asset.asset_no == asset_no).first()
    if not asset:
        asset = Asset(asset_no=asset_no)
        db.add(asset)

    rental_asset_no = value(row, 12)
    kind = value(row, 11) if rental_asset_no else value(row, 6)
    kind = kind or value(row, 5) or value(row, 21)
    asset.asset_type = normalize_asset_type(kind)
    asset.model = value(row, 11) if rental_asset_no else value(row, 6)
    asset.model = asset.model or value(row, 21) or asset.model
    asset.cpu = value(row, 20) or asset.cpu
    asset.memory_gb = to_int(value(row, 22)) or asset.memory_gb
    asset.os = value(row, 24) or asset.os
    asset.purchase_type = "RENTAL" if rental_asset_no else "PURCHASE"
    asset.purchase_date = excel_date(value(row, 9)) or asset.purchase_date
    asset.rental_vendor = "한빛렌탈" if rental_asset_no else asset.rental_vendor
    asset.rental_end_date = asset.rental_end_date
    asset.notes = f"사용자: {value(row, 4)} / 부서: {value(row, 2)}".strip()
    asset.status = "IN_USE" if employee else "STORAGE"

    db.flush()

    if employee:
        active = db.query(AssetAssignment).filter(
            AssetAssignment.asset_id == asset.id,
            AssetAssignment.returned_at.is_(None),
        ).first()
        if not active:
            db.add(AssetAssignment(asset_id=asset.id, employee_id=employee.id))
        elif active.employee_id != employee.id:
            active.employee_id = employee.id

    for product in software_products_from_pc_row(db, row):
        install_software(db, asset, product)

    assign_ip_from_pc_row(db, asset, row)

    return asset


def upsert_rental_contract(db, row: list[str]) -> RentalContract | None:
    asset_no = value(row, 4)
    contract_no = value(row, 2)
    if not asset_no:
        return None

    asset = db.query(Asset).filter(Asset.asset_no == asset_no).first()
    if not asset:
        asset = Asset(
            asset_no=asset_no,
            asset_type=normalize_asset_type(value(row, 3)),
            purchase_type="RENTAL",
            model=value(row, 6),
            serial_no=value(row, 8),
            status="STORAGE",
            rental_vendor="한빛렌탈",
        )
        db.add(asset)
        db.flush()
    else:
        asset.purchase_type = "RENTAL"
        asset.rental_vendor = "한빛렌탈"
        asset.model = asset.model or value(row, 6)
        asset.serial_no = asset.serial_no or value(row, 8)

    contract = db.query(RentalContract).filter(
        RentalContract.asset_id == asset.id,
        RentalContract.contract_no == contract_no,
    ).first()
    if not contract:
        contract = RentalContract(asset_id=asset.id, contract_no=contract_no)
        db.add(contract)

    contract.vendor = "한빛렌탈"
    contract.start_date = excel_date(value(row, 10))
    contract.end_date = excel_date(value(row, 11))
    contract.monthly_fee = to_decimal(value(row, 16))
    contract.status = "ACTIVE" if not value(row, 13) else "ENDED"
    asset.rental_end_date = contract.end_date
    return contract


def sheet_rows(rows: dict, name: str, skip: int, fallback: str = "") -> list:
    """시트가 없으면 조용히 빈 목록을 주지 않고 알린다.

    예전에는 rows.get(name, []) 이라 시트 이름이 바뀌거나 사라져도
    'employees=0' 같은 정상처럼 보이는 결과만 남고 원인을 알 수 없었다.

    fallback 이 있으면 [안내]로 조용히 알린다 — 없어도 다른 경로로 처리되는
    정상 상황이기 때문이다. '경고'라고 쓰면 매번 실패처럼 읽힌다."""
    if name not in rows:
        if fallback:
            print(f"  [안내] '{name}' 시트 없음 → {fallback}")
        else:
            print(f"  [경고] 시트 '{name}' 를 찾을 수 없습니다. 건너뜁니다."
                  f" (파일에 있는 시트: {', '.join(rows.keys())})")
        return []
    return rows[name][skip:]


def find_rental_rows(rows: dict[str, list[list[str]]]) -> list[list[str]]:
    """렌탈 계약 시트를 찾아 데이터 행만 돌려준다.

    시트 이름이 '2026-07' 처럼 월마다 바뀌고 헤더도 1행이 아니라 7행에 있다.
    이름이나 행 번호를 박아두면 다음 달에 또 조용히 0건이 되므로,
    '계약번호' 와 '종료일자' 가 같이 있는 행을 헤더로 보고 그 다음부터 읽는다.
    """
    for sheet_name, sheet_rows in rows.items():
        for idx, row in enumerate(sheet_rows):
            cells = [str(c or "").strip() for c in row]
            if "계약번호" in cells and "종료일자" in cells:
                data = sheet_rows[idx + 1:]
                print(f"  렌탈 시트 '{sheet_name}' 인식 "
                      f"(헤더 {idx + 1}행, 데이터 {len(data)}행)")
                return data
    print("  [경고] 렌탈 계약 시트를 찾지 못했습니다."
          " ('계약번호'와 '종료일자' 헤더가 있는 시트가 필요합니다)")
    return []


def import_rental_file(db) -> int:
    """노트북렌탈.xlsx 를 읽어 렌탈 계약을 등록한다. 파일이 없으면 건너뛴다."""
    path = find_data_file("rental")
    if path is None:
        return 0

    count = 0
    for row in find_rental_rows(load_workbook_rows(path)):
        if upsert_rental_contract(db, row):
            count += 1
    return count


def main() -> None:
    path = find_data_file("pc_list", required=True)
    rows = load_workbook_rows(path)

    db = SessionLocal()
    try:
        db.query(AssetAssignment).filter(
            AssetAssignment.asset_id.in_(
                db.query(Asset.id).filter(Asset.asset_no.like("PC-%"))
            )
        ).delete(synchronize_session=False)
        db.query(IPAssignment).filter(
            IPAssignment.asset_id.in_(
                db.query(Asset.id).filter(Asset.asset_no.like("PC-%"))
            )
        ).delete(synchronize_session=False)
        db.query(SoftwareInstallation).filter(
            SoftwareInstallation.asset_id.in_(
                db.query(Asset.id).filter(Asset.asset_no.like("PC-%"))
            )
        ).delete(synchronize_session=False)
        db.query(Asset).filter(Asset.asset_no.like("PC-%")).delete(
            synchronize_session=False
        )
        db.query(AssetAssignment).filter(
            AssetAssignment.asset_id.in_(
                db.query(Asset.id).filter(Asset.asset_no.like("ROW-%"))
            )
        ).delete(synchronize_session=False)
        db.query(IPAssignment).filter(
            IPAssignment.asset_id.in_(
                db.query(Asset.id).filter(Asset.asset_no.like("ROW-%"))
            )
        ).delete(synchronize_session=False)
        db.query(SoftwareInstallation).filter(
            SoftwareInstallation.asset_id.in_(
                db.query(Asset.id).filter(Asset.asset_no.like("ROW-%"))
            )
        ).delete(synchronize_session=False)
        db.query(Asset).filter(Asset.asset_no.like("ROW-%")).delete(
            synchronize_session=False
        )

        pc_rows = sheet_rows(rows, "PC대장", 2)

        employees = {}
        for row in sheet_rows(rows, "직원리스트", 1,
                              fallback="PC대장에서 직원을 추출합니다 (정상)"):
            employee = upsert_employee(db, row)
            if employee:
                db.flush()
                employees[employee.emp_no] = employee

        # 직원리스트 시트가 없는 파일이면 PC대장에서 담당자를 뽑아낸다.
        # 이게 없으면 자산이 전부 주인 없는 '보관' 상태로 들어간다.
        if not employees:
            for row in pc_rows:
                employee = upsert_employee_from_pc_row(db, row)
                if employee:
                    db.flush()
                    employees[employee.emp_no] = employee
            if employees:
                print(f"  PC대장에서 직원 {len(employees)}명을 추출했습니다.")

        asset_count = 0
        for row in pc_rows:
            if upsert_pc_asset(db, row, employees):
                asset_count += 1

        # 렌탈 계약: PC_list 안의 시트를 먼저 보고, 없으면 별도 파일에서 읽는다.
        rental_count = 0
        for row in sheet_rows(rows, "노트북 임대 리스트", 1,
                              fallback="별도 렌탈 파일(rental.xlsx)에서 읽습니다 (정상)"):
            if upsert_rental_contract(db, row):
                rental_count += 1
        if not rental_count:
            rental_count = import_rental_file(db)

        db.commit()
        print(f"employees={len(employees)} assets_seen={asset_count} rentals_seen={rental_count}")
    except IntegrityError:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
