"""IP 자료 읽고 넣기.

내선번호 넣기(extension_import.py)와 같은 규칙·같은 모양이다. 파일 읽기는
그쪽 것을 그대로 쓴다 — CSV/엑셀을 읽는 법을 두 벌로 두면 한쪽만 고치는
일이 반드시 생긴다.

바깥에서 쓰는 것은 둘뿐이다.
    plan(db, rows, overwrite)  -> 뭐가 들어갈지 (아무것도 안 바꾼다)
    apply_plan(db, planned)    -> 실제로 넣는다

칸 이름은 **내려받기가 내보내는 이름과 같다.** 목록을 받아서 줄만 채워
그대로 올릴 수 있어야 하기 때문이다.
"""

import ipaddress
import uuid

from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.extension import Extension
from app.models.ip_assignment import IPAssignment
from app.models.ip_range import IPRange
from app.services.extension_import import ImportError_, map_headers, read_table  # noqa: F401

# 칸 이름 후보. 왼쪽이 우리가 쓰는 이름.
HEADERS = {
    "ip": ("ip", "아이피", "ip주소", "ip address", "주소"),
    "kind": ("구분", "종류", "kind"),
    "asset_no": ("자산번호", "자산 번호", "자산", "asset", "asset_no"),
    "extension": ("내선", "내선번호", "내선 번호", "extension"),
    "hostname": ("호스트명", "호스트", "장비명", "hostname"),
    "mac": ("mac", "mac주소", "mac address", "맥주소"),
    "note": ("메모", "비고", "note"),
}

PHONE_WORDS = ("전화", "전화기", "phone", "voip")


def _headers(header_row: list[str]) -> dict:
    """map_headers 는 내선용 표를 본다. IP 용 표로 같은 일을 한다."""
    found = {}
    for position, raw in enumerate(header_row):
        label = str(raw or "").strip().lower().replace(" ", "")
        for key, candidates in HEADERS.items():
            if key in found:
                continue
            if any(label == c.lower().replace(" ", "") for c in candidates):
                found[key] = position
    return found


def _valid_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def _range_of(ranges: list[IPRange], ip: str, kind: str):
    """이 IP 가 어느 대역에 드는지 찾는다. 못 찾아도 넣기는 한다 —
    대역을 미처 등록 안 했다고 자료를 못 넣게 막을 이유는 없다."""
    try:
        value = ipaddress.ip_address(ip)
    except ValueError:
        return None
    for item in ranges:
        try:
            if ipaddress.ip_address(item.start_ip) <= value <= ipaddress.ip_address(item.end_ip):
                if item.kind == kind:
                    return item
        except ValueError:
            continue
    return None


def plan(db: Session, rows: list[list[str]], overwrite: bool = False) -> dict:
    """뭐가 들어갈지만 계산한다. DB 는 읽기만 한다.

    건너뛴 줄은 이유를 함께 돌려준다 — '몇 개 실패' 라고만 하면 파일의
    어느 줄을 고쳐야 할지 알 수 없다.
    """
    rows = [row for row in rows if any(str(cell).strip() for cell in row)]
    if not rows:
        raise ImportError_("파일이 비어 있습니다.")

    columns = _headers(rows[0])
    if "ip" not in columns:
        raise ImportError_(
            "'IP' 칸을 못 찾았습니다. 첫 줄에 칸 이름이 있어야 합니다. "
            f"쓸 수 있는 이름: {', '.join(HEADERS['ip'])}"
        )

    def value(row, key):
        index = columns.get(key)
        if index is None or index >= len(row):
            return ""
        return str(row[index] or "").strip()

    assets = {a.asset_no: a for a in db.query(Asset).all() if a.asset_no}
    extensions = {e.number: e for e in db.query(Extension).all()}
    ranges = db.query(IPRange).all()
    existing = {a.ip_address: a for a in db.query(IPAssignment).all()}

    new, update, skipped = [], [], []
    seen = set()

    for line_no, row in enumerate(rows[1:], start=2):
        ip = value(row, "ip")
        if not ip:
            continue
        if not _valid_ip(ip):
            skipped.append(f"{line_no}줄: '{ip}' 는 IP 주소 모양이 아닙니다")
            continue
        if ip in seen:
            skipped.append(f"{line_no}줄: 파일 안에 {ip} 가 두 번 나옵니다")
            continue
        seen.add(ip)

        kind_text = value(row, "kind")
        kind = "PHONE" if any(w in kind_text.lower() for w in PHONE_WORDS) else "NETWORK"

        asset_no = value(row, "asset_no")
        ext_no = value(row, "extension")
        # 내선번호가 적혀 있으면 전화기로 본다. 구분 칸이 비어 있는 파일이 흔하다.
        if ext_no and not kind_text:
            kind = "PHONE"

        asset = None
        if asset_no:
            asset = assets.get(asset_no)
            if asset is None:
                skipped.append(f"{line_no}줄: 자산번호 '{asset_no}' 를 못 찾았습니다")
                continue
            kind = "NETWORK"

        extension = None
        if ext_no:
            extension = extensions.get(ext_no)
            if extension is None:
                skipped.append(f"{line_no}줄: 내선 '{ext_no}' 를 못 찾았습니다 "
                               "(내선 관리에서 먼저 만들어 주세요)")
                continue
            kind = "PHONE"

        if kind == "PHONE" and extension is None:
            skipped.append(f"{line_no}줄: 전화기 IP 인데 내선번호가 없습니다")
            continue

        ip_range = _range_of(ranges, ip, kind)
        item = {
            "ip": ip,
            "kind": kind,
            "asset_no": asset_no,
            "asset_id": str(asset.id) if asset else None,
            "extension": ext_no,
            "extension_id": str(extension.id) if extension else None,
            "hostname": value(row, "hostname"),
            "mac": value(row, "mac"),
            "range_id": str(ip_range.id) if ip_range else None,
            "range_name": ip_range.name if ip_range else "",
        }

        found = existing.get(ip)
        if found is None:
            new.append(item)
        elif found.status == "FREE":
            # 비워 둔 자리다. 덮어쓰기 없이도 채운다.
            update.append(item)
        elif overwrite:
            update.append(item)
        else:
            skipped.append(f"{line_no}줄: {ip} 는 이미 쓰이고 있습니다 "
                           "(덮어쓰려면 아래 '이미 있는 것도 덮어쓰기' 를 켜세요)")

    return {"columns": [k for k in columns], "new": new, "update": update, "skipped": skipped}


def apply_plan(db: Session, planned: dict) -> dict:
    """plan() 이 만든 계획을 그대로 넣는다. 계획에 없는 일은 하지 않는다."""
    existing = {a.ip_address: a for a in db.query(IPAssignment).all()}

    def fill(target, item):
        target.kind = item["kind"]
        target.asset_id = uuid.UUID(item["asset_id"]) if item["asset_id"] else None
        target.extension_id = uuid.UUID(item["extension_id"]) if item["extension_id"] else None
        target.ip_range_id = uuid.UUID(item["range_id"]) if item["range_id"] else None
        target.hostname = item["hostname"] or None
        target.mac_address = item["mac"] or None
        target.status = "USED"

    for item in planned["new"]:
        row = IPAssignment(id=uuid.uuid4(), ip_address=item["ip"])
        fill(row, item)
        db.add(row)

    for item in planned["update"]:
        row = existing.get(item["ip"])
        if not row:
            continue
        # 한 내선에 IP 가 둘이 되지 않게, 그 내선에 붙어 있던 다른 IP 는 뗀다.
        if item["extension_id"]:
            db.query(IPAssignment).filter(
                IPAssignment.extension_id == uuid.UUID(item["extension_id"]),
                IPAssignment.ip_address != item["ip"],
            ).update({"extension_id": None, "status": "FREE"}, synchronize_session=False)
        fill(row, item)

    db.commit()
    return {"added": len(planned["new"]), "updated": len(planned["update"])}
