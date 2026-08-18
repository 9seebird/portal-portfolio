"""라이선스(lisence.xlsx)와 IP 대역/소프트웨어 사용현황(IT_SW_Userlist)을 DB에 넣는다.

PC대장(sync_from_excel.py)이 자산·직원·설치SW를 담당하는 것과 별개로,
이 스크립트는 아래 세 가지를 채운다.
  - 라이선스: lisence.xlsx 의 18종(품명·수량·만료일) → SoftwareProduct + LicensePool
  - 사용수량: IT_SW_Userlist 'SW 리스트'의 사용자별 ○ 를 세어 라이선스 used_count 에 반영
  - IP 대역: IT_SW_Userlist 'IP 음성/3F/4F' 시트의 네트워크 정보 → IPRange

사용법:
    python scripts/import_licenses_ip.py            # dry-run (아무것도 바꾸지 않음)
    python scripts/import_licenses_ip.py --apply    # 실제 반영
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
from app.models.ip_range import IPRange
from app.models.license_pool import LicensePool
from app.models.software_product import SoftwareProduct

from scripts.datafiles import find_data_file

# 파일명을 박아두지 않는다. 버전이 붙거나 이름이 바뀌어도 찾아낸다.
# (예전에는 IT_SW_Userlist_v2.2_2607.xlsx 처럼 버전이 박혀 있어서
#  새 버전을 받으면 조용히 0건이 되었다)
LICENSE_XLSX = find_data_file("license", required=True)
SW_XLSX = find_data_file("sw_userlist", required=True)

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"a": MAIN_NS}

# 'SW 리스트'의 소프트웨어 컬럼명 → 라이선스 품명(lisence.xlsx) 매핑.
# 시트 컬럼과 라이선스가 1:1로 명확히 대응하는 것만 넣는다.
# (MSoffice·rhino·fineprint·zoom 은 대응 라이선스가 없어 제외)
SW_TO_LICENSE = {
    "O365": "Microsoft 365 비즈니스용 앱",
    "한글": "한컴오피스_한/글 ALA 9.0",
    "Adobe": "Creative Cloud for Teams 모든 앱",
    "Paralles": "Parallels 데스크톱 비즈니스",
    "keyshot": "KeyShot Studio 프로페셔널",
    "윤폰트": "윤콜렉션 Thin 기업용",
}


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
                "".join(t.text or "" for t in si.iter(f"{{{MAIN_NS}}}t"))
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
                values[idx] = text
            rows.append(values)
        return rows


def clean(text: str) -> str:
    return text.replace("\xa0", " ").strip()


def excel_date(raw: str) -> date | None:
    raw = raw.strip()
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


def to_int(raw: str) -> int:
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------- 파싱

def vendor_of(name: str) -> str | None:
    table = {
        "Microsoft": "Microsoft", "Kaspersky": "Kaspersky", "Adobe": "Adobe",
        "포토샵": "Adobe", "Parallels": "Parallels", "KeyShot": "Luxion",
        "한컴": "한글과컴퓨터", "한/글": "한글과컴퓨터", "산돌": "산돌",
        "윤콜렉션": "윤디자인", "OfficeKeeper": "OfficeKeeper",
    }
    for keyword, vendor in table.items():
        if keyword in name:
            return vendor
    return None


def parse_licenses() -> list[dict]:
    rows = load_sheet(LICENSE_XLSX, "Sheet1")
    licenses = []
    for row in rows[1:]:
        name = clean(row[1]) if len(row) > 1 else ""
        if not name:
            continue
        licenses.append({
            "name": name,
            "vendor": vendor_of(name),
            "purchased": to_int(row[2]) if len(row) > 2 else 0,
            "expire": excel_date(row[3]) if len(row) > 3 else None,
        })
    return licenses


def parse_sw_usage() -> dict[str, int]:
    """'SW 리스트'에서 SW_TO_LICENSE 컬럼별 ○ 개수를 센다."""
    rows = load_sheet(SW_XLSX, "SW 리스트")
    header = [clean(c) for c in rows[3]]           # r3: 컬럼명(win10.., O365, 한글 ...)
    name_col = 2                                   # 성명

    col_of = {}
    for sw_name in SW_TO_LICENSE:
        if sw_name in header:
            col_of[sw_name] = header.index(sw_name)

    usage = {sw: 0 for sw in col_of}
    for row in rows[5:]:                           # r5 부터 사용자 행
        person = clean(row[name_col]) if len(row) > name_col else ""
        if not person or person == "합 계":
            continue
        for sw_name, idx in col_of.items():
            if idx < len(row) and clean(row[idx]):
                usage[sw_name] += 1
    return usage


def parse_ip_ranges() -> list[dict]:
    """'IP 음성/3F/4F' 시트 A2 블록에서 네트워크 정보를 뽑는다.

    A2 예: '4F\\n10.20.30.0\\n255.255.255.0\\n10.20.30.1\\n168.126.63.1'
           (라벨 / 네트워크 / 서브넷마스크 / 게이트웨이 / DNS)
    """
    ranges = []
    for sheet, name in (("IP 음성", "음성"), ("IP 3F", "3F"), ("IP 4F", "4F")):
        rows = load_sheet(SW_XLSX, sheet)
        block = rows[1][0] if len(rows) > 1 and rows[1] else ""
        parts = [p.strip() for p in block.split("\n") if p.strip()]
        network = next((p for p in parts if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", p) and p.endswith(".0")), None)
        if not network:
            continue
        base = network.rsplit(".", 1)[0]
        ips = [p for p in parts if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", p)]
        mask = next((p for p in ips if p.startswith("255.")), None)
        others = [p for p in ips if p != network and p != mask]
        gateway = others[0] if others else None
        dns = others[1] if len(others) > 1 else None
        ranges.append({
            "name": name,
            "start_ip": f"{base}.2",
            "end_ip": f"{base}.254",
            "gateway": gateway,
            "dns": dns,
            "description": f"{network}/{mask}" if mask else network,
        })
    return ranges


# ---------------------------------------------------------------- 반영

def run(apply: bool) -> None:
    licenses = parse_licenses()
    usage = parse_sw_usage()
    ranges = parse_ip_ranges()

    # SW 컬럼 사용수량 → 라이선스 품명별 used_count
    used_by_license = {}
    for sw_name, count in usage.items():
        used_by_license[SW_TO_LICENSE[sw_name]] = count

    db = SessionLocal()
    log: list[str] = []
    try:
        for lic in licenses:
            product = db.query(SoftwareProduct).filter(
                SoftwareProduct.name == lic["name"]
            ).first()
            if not product:
                product = SoftwareProduct(
                    name=lic["name"], vendor=lic["vendor"], license_type="VOLUME"
                )
                db.add(product)
                db.flush()
                log.append(f"제품 신규   {lic['name']}")
            else:
                product.vendor = product.vendor or lic["vendor"]
                log.append(f"제품 유지   {lic['name']}")

            used = used_by_license.get(lic["name"])
            pool = db.query(LicensePool).filter(
                LicensePool.software_id == product.id
            ).first()
            if not pool:
                pool = LicensePool(software_id=product.id)
                db.add(pool)
                log.append(f"라이선스 신규 {lic['name']}  보유{lic['purchased']} 사용{used if used is not None else '-'}")
            else:
                log.append(f"라이선스 갱신 {lic['name']}  보유{lic['purchased']} 사용{used if used is not None else '-'}")
            pool.purchased_count = lic["purchased"]
            pool.expire_date = lic["expire"]
            if used is not None:
                pool.used_count = used
            db.flush()

        for rng in ranges:
            existing = db.query(IPRange).filter(IPRange.name == rng["name"]).first()
            if not existing:
                db.add(IPRange(**rng))
                log.append(f"IP대역 신규  {rng['name']}  {rng['start_ip']}~{rng['end_ip']} gw {rng['gateway']}")
            else:
                for key, value in rng.items():
                    setattr(existing, key, value)
                log.append(f"IP대역 갱신  {rng['name']}  {rng['start_ip']}~{rng['end_ip']} gw {rng['gateway']}")
            db.flush()

        for line in log:
            print(" ", line)
        print(f"\n라이선스 {len(licenses)}종 · IP대역 {len(ranges)}개")
        print("SW 사용수량 집계:", {SW_TO_LICENSE[k]: v for k, v in usage.items()})

        if apply:
            db.commit()
            print("\n>>> DB에 반영했습니다.")
        else:
            db.rollback()
            print("\n>>> DRY-RUN: 반영하려면 --apply")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="실제로 DB에 반영")
    args = parser.parse_args()
    run(apply=args.apply)
