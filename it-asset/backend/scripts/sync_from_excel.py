"""PC대장(엑셀)을 기준으로 DB를 동기화한다.

엑셀 data/PC_list.xlsx 의 'PC대장' 시트가 자산대장 원본이다.
  - 자산: PC대장에 있는 행이 정답. 엑셀에 없는 자산은 (--prune 사용 시) 삭제한다.
  - 직원: PC대장의 사번/사용자로 upsert 한다. 엑셀에는 이메일·연락처가 없으므로
          DB에 이미 있는 값은 덮어쓰지 않고 보존한다. 직원은 자동 삭제하지 않는다.
  - 지급/IP/소프트웨어: PC대장 행 기준으로 맞춘다.

사용법:
    python scripts/sync_from_excel.py            # dry-run (아무것도 바꾸지 않음)
    python scripts/sync_from_excel.py --apply    # 실제 반영
    python scripts/sync_from_excel.py --apply --prune   # 엑셀에 없는 자산까지 삭제
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.database import SessionLocal
from app.models.asset import Asset
from app.models.asset_assignment import AssetAssignment
from app.models.employee import Employee
from app.models.ip_assignment import IPAssignment
from app.models.rental_contract import RentalContract
from app.models.software_installation import SoftwareInstallation
from app.models.software_product import SoftwareProduct

from scripts.datafiles import find_data_file

EXCEL_PATH = find_data_file("pc_list", required=True)
SHEET = "PC대장"

# PC대장은 2줄 헤더다.
#   1행: 그룹  ─ 구분 / H/W (구매) / H/W (임대) / S/W
#   2행: 컬럼명 ─ 순번, 지역, ... (그룹 안에서 "종류", "자산번호"가 중복된다)
# 컬럼 위치가 자주 바뀌므로 인덱스를 박아두지 않고 헤더 이름으로 찾는다.
GROUP_ROW = 0
HEADER_ROW = 1
DATA_START = 2

BUY = "H/W (구매)"
RENT = "H/W (임대)"

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"a": MAIN_NS}


# ---------------------------------------------------------------- 엑셀 읽기

def col_index(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref).group(0)
    value = 0
    for ch in letters:
        value = value * 26 + ord(ch) - 64
    return value - 1


def load_sheet(path: Path, sheet_name: str) -> list[list[str]]:
    with ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = [
                "".join(t.text or "" for t in si.iter(f"{{{MAIN_NS}}}t")).strip()
                for si in root.findall("a:si", NS)
            ]

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

        target = None
        names = []
        for sheet in workbook.find("a:sheets", NS):
            names.append(sheet.attrib["name"])
            if sheet.attrib["name"] == sheet_name:
                target = "xl/" + relmap[sheet.attrib[f"{{{REL_NS}}}id"]].lstrip("/")
        if not target:
            raise SystemExit(f"'{sheet_name}' 시트를 찾을 수 없습니다. 현재 시트: {names}")

        root = ET.fromstring(archive.read(target))
        rows = []
        for row in root.findall(".//a:sheetData/a:row", NS):
            values: list[str] = []
            for cell in row.findall("a:c", NS):
                idx = col_index(cell.attrib["r"])
                while len(values) <= idx:
                    values.append("")
                node = cell.find("a:v", NS)
                text = "" if node is None else (node.text or "")
                if cell.attrib.get("t") == "s" and text:
                    text = shared[int(text)]
                values[idx] = text.strip()
            rows.append(values)
        return rows


class Columns:
    """2줄 헤더에서 컬럼 위치를 이름으로 찾아준다.

    "종류"와 "자산번호"는 구매/임대 그룹에 중복으로 존재하므로 group 인자로 구분한다.
    엑셀에서 컬럼이 추가/삭제되어 위치가 밀려도 그대로 동작한다.
    """

    def __init__(self, sheet: list[list[str]]) -> None:
        groups = sheet[GROUP_ROW]
        headers = sheet[HEADER_ROW]

        # 1행의 그룹명은 병합셀이라 시작 컬럼에만 있다. 다음 그룹 전까지 이어서 채운다.
        self.group_of: list[str] = []
        current = ""
        for i in range(len(headers)):
            marker = groups[i].strip() if i < len(groups) and groups[i] else ""
            if marker:
                current = marker
            self.group_of.append(current)

        self.headers = [h.strip() if h else "" for h in headers]

    def find(self, name: str, group: str | None = None) -> int:
        for i, header in enumerate(self.headers):
            if header != name:
                continue
            if group is None or self.group_of[i] == group:
                return i
        raise SystemExit(
            f"PC대장에서 '{name}'"
            + (f" ({group} 그룹)" if group else "")
            + f" 컬럼을 찾을 수 없습니다. 현재 헤더: {self.headers}"
        )

    def get(self, row: list[str], name: str, group: str | None = None) -> str:
        index = self.find(name, group)
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
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 행 해석

def ip_or_none(raw: str) -> str | None:
    if not raw or raw.strip().upper() in {"X", "-"}:
        return None
    return raw.strip()


def asset_type_of(kind: str) -> str:
    if "노트북" in kind:
        return "LAPTOP"
    if "데스크" in kind:
        return "DESKTOP"
    if "모니터" in kind:
        return "MONITOR"
    if "서버" in kind:
        return "SERVER"
    return "OTHER"


def software_names(cols: Columns, row: list[str]) -> list[tuple[str, str]]:
    """PC대장 S/W 컬럼을 (제품명, 벤더) 목록으로 바꾼다. 'X'/공란은 미설치."""
    products: list[tuple[str, str]] = []

    office = cols.get(row, "오피스")
    if office and office.upper() != "X":
        name = "Microsoft 365" if office.upper() == "O365" else f"Microsoft Office {office}"
        products.append((name, "Microsoft"))

    if cols.get(row, "카스퍼스키").upper() == "O":
        products.append(("Kaspersky Endpoint Security", "Kaspersky"))

    hancom = cols.get(row, "한글")
    if hancom.upper() == "O":
        products.append(("한글", "한글과컴퓨터"))
    elif hancom and hancom.upper() != "X":
        # 셀에 2020, 2020.2007000000001 같은 값이 섞여 있어 연도만 취한다.
        products.append((f"한글 {hancom.split('.')[0]}", "한글과컴퓨터"))

    windows = cols.get(row, "윈도우")
    if windows and windows.upper() not in {"X", "O"}:
        products.append((f"Windows {windows}", "Microsoft"))

    return products


def parse_rows(sheet: list[list[str]]) -> list[dict]:
    cols = Columns(sheet)
    parsed = []
    for row in sheet[DATA_START:]:
        seq = cols.get(row, "순번")
        emp_no = cols.get(row, "사번")
        if not seq and not emp_no:
            continue

        rent_no = cols.get(row, "자산번호", RENT)
        kind = cols.get(row, "종류", "구분")
        is_rental = bool(rent_no) or "임대" in kind

        notes_bits = [
            f"보관장소: {cols.get(row, '보관장소')}" if cols.get(row, "보관장소") else "",
            f"분류: {cols.get(row, '분류')}" if cols.get(row, "분류") else "",
            f"비고: {cols.get(row, '비고')}" if cols.get(row, "비고") else "",
        ]

        parsed.append(
            {
                "source_key": f"PC:{seq}",
                "asset_no": rent_no or cols.get(row, "자산번호/일련번호", BUY) or None,
                "label_no": cols.get(row, "라벨 번호", BUY) or None,
                "asset_type": asset_type_of(kind),
                "alias": cols.get(row, "종류", RENT if is_rental else BUY),
                "cpu": cols.get(row, "CPU") or None,
                "memory_gb": to_int(cols.get(row, "메모리")),
                "os": cols.get(row, "운영체제") or None,
                "purchase_type": "RENTAL" if is_rental else "PURCHASE",
                "purchase_date": excel_date(
                    cols.get(row, "최초임대", RENT) if is_rental
                    else cols.get(row, "구입시기", BUY)
                ),
                "rental_vendor": "한빛렌탈" if is_rental else None,
                "monthly_fee": to_int(cols.get(row, "월정료", RENT)),
                "notes": " / ".join(bit for bit in notes_bits if bit) or None,
                # IP 칸에 'x'(미할당)를 적어둔 행이 있어 주소로 취급하면 안 된다.
                "ip": ip_or_none(cols.get(row, "IP")),
                "software": software_names(cols, row),
                "emp_no": emp_no or None,
                "emp_name": cols.get(row, "사용자") or None,
                "department": cols.get(row, "팀명/사용층") or None,
                "location": cols.get(row, "지역") or None,
            }
        )
    return parsed


# ---------------------------------------------------------------- 동기화

class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.counts: dict[str, int] = {}

    def add(self, kind: str, detail: str = "") -> None:
        self.counts[kind] = self.counts.get(kind, 0) + 1
        if detail:
            self.lines.append(f"  {kind}: {detail}")

    def dump(self) -> None:
        for line in self.lines:
            print(line)
        print("\n요약")
        for kind, count in sorted(self.counts.items()):
            print(f"  {kind:24s} {count}")


def ensure_product(db, name: str, vendor: str, cache: dict) -> SoftwareProduct:
    if name in cache:
        return cache[name]
    product = db.query(SoftwareProduct).filter(SoftwareProduct.name == name).first()
    if not product:
        product = SoftwareProduct(name=name, vendor=vendor, license_type="DEVICE")
        db.add(product)
        db.flush()
    cache[name] = product
    return product


def sync(apply: bool, prune: bool) -> None:
    rows = parse_rows(load_sheet(EXCEL_PATH, SHEET))
    print(f"엑셀 '{SHEET}' 유효 행: {len(rows)}\n")

    db = SessionLocal()
    report = Report()
    product_cache: dict = {}

    try:
        # ---- 직원: PC대장 사번 기준 upsert (이메일/연락처 등 기존 값은 보존)
        employees: dict[str, Employee] = {}
        for row in rows:
            emp_no = row["emp_no"]
            if not emp_no or emp_no in employees:
                continue
            employee = db.query(Employee).filter(Employee.emp_no == emp_no).first()
            if not employee:
                employee = Employee(emp_no=emp_no, name=row["emp_name"] or emp_no)
                db.add(employee)
                report.add("직원 신규", f"{emp_no} {row['emp_name']}")
            else:
                report.add("직원 유지")
            employee.name = row["emp_name"] or employee.name
            employee.department = row["department"] or employee.department
            employee.location = row["location"] or employee.location
            employee.status = "ACTIVE"
            db.flush()
            employees[emp_no] = employee

        db_only = (
            db.query(Employee)
            .filter(~Employee.emp_no.in_(list(employees) or [""]))
            .all()
        )
        stale_employee_ids = set()
        for employee in db_only:
            label = f"{employee.emp_no} {employee.name}"
            if prune:
                stale_employee_ids.add(employee.id)
                report.add("직원 삭제(엑셀에 없음)", label)
            else:
                report.add("직원 엑셀에 없음(유지)", label)

        # ---- 자산: source_key(PC:순번) 또는 asset_no 로 매칭
        seen_ids = set()
        for row in rows:
            asset = None
            if row["asset_no"]:
                asset = db.query(Asset).filter(Asset.asset_no == row["asset_no"]).first()
            if not asset:
                asset = (
                    db.query(Asset).filter(Asset.source_key == row["source_key"]).first()
                )
            if not asset:
                asset = Asset()
                db.add(asset)
                report.add("자산 신규", f"{row['asset_no'] or '(번호미부여)'} {row['alias']}")
            else:
                report.add("자산 갱신")

            asset.source_key = row["source_key"]
            asset.asset_no = row["asset_no"]
            asset.label_no = row["label_no"]
            asset.asset_type = row["asset_type"]
            asset.cpu = row["cpu"]
            asset.memory_gb = row["memory_gb"]
            asset.os = row["os"]
            asset.purchase_type = row["purchase_type"]
            asset.purchase_date = row["purchase_date"]
            asset.rental_vendor = row["rental_vendor"] or asset.rental_vendor
            asset.notes = row["notes"]
            # 엑셀에는 실제 모델명이 없다. DB에 이미 모델명이 있으면 그대로 두고,
            # 없을 때만 엑셀의 내부 별칭("데스크탑1", "LG노트북 임대")을 넣는다.
            if not asset.model:
                asset.model = row["alias"] or None
            asset.status = "IN_USE" if row["emp_no"] else "STORAGE"
            db.flush()
            seen_ids.add(asset.id)

            # 지급 이력
            employee = employees.get(row["emp_no"]) if row["emp_no"] else None
            active = (
                db.query(AssetAssignment)
                .filter(
                    AssetAssignment.asset_id == asset.id,
                    AssetAssignment.returned_at.is_(None),
                )
                .first()
            )
            if employee:
                if not active:
                    db.add(AssetAssignment(asset_id=asset.id, employee_id=employee.id))
                    report.add("자산 지급")
                elif active.employee_id != employee.id:
                    active.employee_id = employee.id
                    report.add("자산 사용자 변경")
            elif active:
                active.returned_at = datetime.utcnow()
                report.add("자산 회수(사용자 없음)")

            # IP: 엑셀 값이 정답. 자산에 붙은 다른 IP는 정리한다.
            for existing in db.query(IPAssignment).filter(
                IPAssignment.asset_id == asset.id
            ):
                if existing.ip_address != row["ip"]:
                    db.delete(existing)
                    report.add("IP 해제")
            if row["ip"]:
                held = (
                    db.query(IPAssignment)
                    .filter(IPAssignment.ip_address == row["ip"])
                    .first()
                )
                if held and held.asset_id != asset.id:
                    held.asset_id = asset.id
                    held.status = "USED"
                    report.add("IP 재배정")
                elif not held:
                    db.add(
                        IPAssignment(
                            asset_id=asset.id,
                            ip_address=row["ip"],
                            hostname=row["emp_name"],
                            status="USED",
                        )
                    )
                    report.add("IP 신규")
                else:
                    held.status = "USED"
                    held.hostname = held.hostname or row["emp_name"]

            # 소프트웨어: 엑셀 값이 정답
            wanted = {}
            for name, vendor in row["software"]:
                wanted[name] = ensure_product(db, name, vendor, product_cache)
            current = (
                db.query(SoftwareInstallation, SoftwareProduct)
                .join(
                    SoftwareProduct,
                    SoftwareProduct.id == SoftwareInstallation.software_id,
                )
                .filter(SoftwareInstallation.asset_id == asset.id)
                .all()
            )
            current_names = set()
            for installation, product in current:
                if product.name not in wanted:
                    db.delete(installation)
                    report.add("SW 제거")
                else:
                    current_names.add(product.name)
            for name, product in wanted.items():
                if name not in current_names:
                    db.add(
                        SoftwareInstallation(asset_id=asset.id, software_id=product.id)
                    )
                    report.add("SW 설치")

            # 임대 계약: 계약번호/만료일은 엑셀에 없으므로 기존 계약을 보존하고,
            # 계약이 없을 때만 월정료 기준으로 최소 정보를 만든다.
            if row["purchase_type"] == "RENTAL":
                contract = (
                    db.query(RentalContract)
                    .filter(RentalContract.asset_id == asset.id)
                    .first()
                )
                if not contract:
                    db.add(
                        RentalContract(
                            asset_id=asset.id,
                            vendor="한빛렌탈",
                            start_date=row["purchase_date"],
                            monthly_fee=row["monthly_fee"],
                            status="ACTIVE",
                        )
                    )
                    report.add("임대계약 신규")

        # ---- 엑셀에 없는 자산
        # 위에서 IP를 다른 자산으로 재배정한 변경분을 먼저 DB에 반영해야,
        # 아래 asset_id 기준 삭제가 재배정된 IP까지 지워버리지 않는다.
        db.flush()

        extras = db.query(Asset).filter(~Asset.id.in_(seen_ids or [None])).all()
        for asset in extras:
            label = f"{asset.asset_no or '(번호없음)'} / {asset.model or '-'} / {asset.status}"
            if prune:
                for model in (
                    IPAssignment,
                    SoftwareInstallation,
                    RentalContract,
                    AssetAssignment,
                ):
                    db.query(model).filter(model.asset_id == asset.id).delete(
                        synchronize_session="fetch"
                    )
                db.delete(asset)
                report.add("자산 삭제(엑셀에 없음)", label)
            else:
                report.add("자산 엑셀에 없음(유지)", label)

        # 자산을 정리한 뒤에야 직원을 지울 수 있다(지급 이력이 직원을 참조하므로).
        # synchronize_session="fetch": 세션이 들고 있는 지급이력 객체까지 삭제로 표시해야
        # 위에서 returned_at을 수정해 둔 행을 다시 UPDATE 하려다 StaleDataError가 나지 않는다.
        for employee_id in stale_employee_ids:
            db.query(AssetAssignment).filter(
                AssetAssignment.employee_id == employee_id
            ).delete(synchronize_session="fetch")
            db.query(Employee).filter(Employee.id == employee_id).delete(
                synchronize_session="fetch"
            )

        if apply:
            db.commit()
            print(">>> 변경사항을 DB에 반영했습니다.\n")
        else:
            db.rollback()
            print(">>> DRY-RUN: DB는 변경하지 않았습니다. 반영하려면 --apply\n")

        report.dump()
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="실제로 DB에 반영")
    parser.add_argument(
        "--prune", action="store_true", help="엑셀(PC대장)에 없는 자산을 삭제"
    )
    args = parser.parse_args()
    sync(apply=args.apply, prune=args.prune)
