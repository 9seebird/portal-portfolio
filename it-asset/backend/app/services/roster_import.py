"""직원 명단·자산 자료 읽고 넣기.

내선·IP 넣기와 같은 규칙·같은 모양이다. 파일 읽기는 extension_import 것을
그대로 쓴다 — CSV/엑셀 읽는 법을 여러 벌로 두면 한쪽만 고치는 일이 생긴다.

칸 이름은 화면의 「CSV 내려받기」가 내보내는 것과 같다. 목록을 받아서
줄만 채워 그대로 올릴 수 있어야 하기 때문이다.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.asset_assignment import AssetAssignment
from app.models.employee import Employee
from app.services.extension_import import ImportError_, read_table  # noqa: F401


def _headers(header_row: list[str], table: dict) -> dict:
    found = {}
    for position, raw in enumerate(header_row):
        label = str(raw or "").strip().lower().replace(" ", "")
        for key, candidates in table.items():
            if key in found:
                continue
            if any(label == c.lower().replace(" ", "") for c in candidates):
                found[key] = position
    return found


def _reader(row, columns):
    def value(key):
        index = columns.get(key)
        if index is None or index >= len(row):
            return ""
        return str(row[index] or "").strip()
    return value


def _date(text: str):
    """엑셀에서 나오는 여러 날짜 모양을 받아 준다. 못 읽으면 그냥 비운다 —
    날짜 하나 때문에 줄 전체를 버리는 건 과하다."""
    text = (text or "").strip()
    if not text:
        return None
    for form in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, form).date()
        except ValueError:
            continue
    return None


# ── 직원 명단 ────────────────────────────────────────────────
EMP_HEADERS = {
    "emp_no": ("사번", "사원번호", "emp_no", "employee_no"),
    "name": ("이름", "성명", "name"),
    "department": ("부서", "소속", "팀", "department"),
    "position": ("직책", "직위", "position"),
    "status": ("상태", "재직여부", "status"),
    "email": ("이메일", "메일", "email"),
    "hire_date": ("입사일", "입사", "hire_date", "joined_at"),
    "phone": ("전화", "휴대폰", "연락처", "phone"),
}

RESIGN_WORDS = ("퇴사", "퇴직", "inactive", "resign")
LEAVE_WORDS = ("휴직", "leave")


def plan_employees(db: Session, rows: list[list[str]], overwrite: bool = False) -> dict:
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        raise ImportError_("파일이 비어 있습니다.")

    columns = _headers(rows[0], EMP_HEADERS)
    if "emp_no" not in columns or "name" not in columns:
        raise ImportError_(
            "'사번' 과 '이름' 칸이 모두 있어야 합니다. 첫 줄에 칸 이름을 넣어 주세요. "
            "(사번이 없으면 같은 이름을 구별할 수 없습니다)"
        )

    existing = {e.emp_no: e for e in db.query(Employee).all()}
    new, update, skipped = [], [], []
    seen = set()

    for line_no, row in enumerate(rows[1:], start=2):
        value = _reader(row, columns)
        emp_no, name = value("emp_no"), value("name")
        if not emp_no and not name:
            continue
        if not emp_no:
            skipped.append(f"{line_no}줄: '{name}' 의 사번이 비어 있습니다")
            continue
        if not name:
            skipped.append(f"{line_no}줄: 사번 {emp_no} 의 이름이 비어 있습니다")
            continue
        if emp_no in seen:
            skipped.append(f"{line_no}줄: 파일 안에 사번 {emp_no} 가 두 번 나옵니다")
            continue
        seen.add(emp_no)

        text = value("status").lower()
        status = ("INACTIVE" if any(w in text for w in RESIGN_WORDS)
                  else "LEAVE" if any(w in text for w in LEAVE_WORDS)
                  else "ACTIVE")

        item = {
            "emp_no": emp_no, "name": name,
            "department": value("department"), "position": value("position"),
            "email": value("email"), "phone": value("phone"),
            "status": status, "hire_date": value("hire_date"),
        }

        if emp_no not in existing:
            new.append(item)
        elif overwrite:
            update.append(item)
        else:
            skipped.append(f"{line_no}줄: 사번 {emp_no} 는 이미 있습니다 "
                           "(고치려면 아래 덮어쓰기를 켜세요)")

    return {"columns": list(columns), "new": new, "update": update, "skipped": skipped}


def apply_employees(db: Session, planned: dict) -> dict:
    existing = {e.emp_no: e for e in db.query(Employee).all()}

    def fill(target, item):
        target.name = item["name"]
        target.department = item["department"] or None
        target.position = item["position"] or None
        target.email = item["email"] or None
        target.phone = item["phone"] or None
        target.status = item["status"]
        hire = _date(item["hire_date"])
        if hire:
            target.hire_date = hire

    for item in planned["new"]:
        row = Employee(id=uuid.uuid4(), emp_no=item["emp_no"], name=item["name"])
        fill(row, item)
        db.add(row)

    for item in planned["update"]:
        row = existing.get(item["emp_no"])
        if row:
            fill(row, item)

    db.commit()
    return {"added": len(planned["new"]), "updated": len(planned["update"])}


# ── 자산 ─────────────────────────────────────────────────────
ASSET_HEADERS = {
    "asset_no": ("자산번호", "자산 번호", "관리번호", "asset_no"),
    "label_no": ("라벨번호", "라벨", "label_no"),
    # '구분' 은 내려받기에서 **구매/임대**를 뜻한다. 유형(노트북·모니터)이
    # 아니다. 두 곳에 다 넣어 두면 먼저 걸리는 쪽이 가져가서, 임대 자산이
    # 전부 구매로 들어간다.
    "asset_type": ("유형", "종류", "자산유형", "asset_type", "type"),
    "purchase_type": ("구분", "구매구분", "구입구분", "취득", "purchase_type"),
    "manufacturer": ("제조사", "브랜드", "manufacturer"),
    "model": ("모델", "모델명", "model"),
    "serial_no": ("시리얼", "s/n", "serial", "serial_no"),
    "cpu": ("cpu", "프로세서"),
    "memory_gb": ("메모리", "ram", "memory"),
    "storage_gb": ("저장장치", "디스크", "storage"),
    "os": ("운영체제", "os"),
    "status": ("상태", "status"),
    "holder": ("사용자", "쓰는사람", "보유자", "holder"),
    "notes": ("메모", "비고", "notes"),
}

TYPE_WORDS = {
    "LAPTOP": ("노트북", "랩탑", "laptop", "notebook"),
    "DESKTOP": ("데스크탑", "데스크톱", "pc", "desktop"),
    "MONITOR": ("모니터", "monitor"),
    "SERVER": ("서버", "server"),
    "NETWORK": ("네트워크", "스위치", "공유기", "network"),
}
STATUS_WORDS = {
    "IN_USE": ("사용", "사용중", "in_use", "쓰는"),
    "STORAGE": ("보관", "재고", "storage"),
    "REPAIR": ("수리", "as", "repair"),
    "DISPOSED": ("폐기", "불용", "disposed"),
}


def _pick(text: str, table: dict, default: str) -> str:
    low = (text or "").strip().lower().replace(" ", "")
    if not low:
        return default
    for key, words in table.items():
        if low == key.lower() or any(w in low for w in words):
            return key
    return default


def _int(text: str):
    digits = "".join(c for c in (text or "") if c.isdigit())
    return int(digits) if digits else None


def plan_assets(db: Session, rows: list[list[str]], overwrite: bool = False) -> dict:
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        raise ImportError_("파일이 비어 있습니다.")

    columns = _headers(rows[0], ASSET_HEADERS)
    if "asset_no" not in columns:
        raise ImportError_(
            "'자산번호' 칸을 못 찾았습니다. 첫 줄에 칸 이름이 있어야 합니다. "
            f"쓸 수 있는 이름: {', '.join(ASSET_HEADERS['asset_no'])}"
        )

    existing = {a.asset_no: a for a in db.query(Asset).all() if a.asset_no}
    employees = db.query(Employee).filter(Employee.status == "ACTIVE").all()
    by_emp_no = {e.emp_no: e for e in employees if e.emp_no}
    by_name: dict[str, list[Employee]] = {}
    for e in employees:
        by_name.setdefault(e.name.strip(), []).append(e)

    new, update, skipped = [], [], []
    seen = set()

    for line_no, row in enumerate(rows[1:], start=2):
        value = _reader(row, columns)
        asset_no = value("asset_no")
        if not asset_no:
            continue
        if asset_no in seen:
            skipped.append(f"{line_no}줄: 파일 안에 자산번호 {asset_no} 가 두 번 나옵니다")
            continue
        seen.add(asset_no)

        holder_text = value("holder")
        holder = None
        if holder_text and holder_text != "-":
            holder = by_emp_no.get(holder_text)
            if holder is None:
                matches = by_name.get(holder_text, [])
                if len(matches) == 1:
                    holder = matches[0]
                elif len(matches) > 1:
                    skipped.append(f"{line_no}줄: '{holder_text}' 이 {len(matches)}명입니다 "
                                   "(사용자 칸에 사번을 넣어 주세요)")
                    continue
                else:
                    skipped.append(f"{line_no}줄: '{holder_text}' 을 재직자 명단에서 못 찾았습니다")
                    continue

        item = {
            "asset_no": asset_no,
            "label_no": value("label_no"),
            "asset_type": _pick(value("asset_type"), TYPE_WORDS, "OTHER"),
            # 화면의 등록 폼과 같은 값을 쓴다 (PURCHASE / RENTAL).
            # 여기서만 다른 말을 쓰면 목록 필터에 안 걸린다.
            "purchase_type": ("RENTAL" if any(w in value("purchase_type")
                                              for w in ("임대", "렌탈", "rental"))
                              else "PURCHASE"),
            "manufacturer": value("manufacturer"), "model": value("model"),
            "serial_no": value("serial_no"), "cpu": value("cpu"),
            "memory_gb": _int(value("memory_gb")), "storage_gb": _int(value("storage_gb")),
            "os": value("os"), "notes": value("notes"),
            "status": _pick(value("status"), STATUS_WORDS, "IN_USE" if holder else "STORAGE"),
            "holder_name": holder.name if holder else "",
            "holder_id": str(holder.id) if holder else None,
        }

        if asset_no not in existing:
            new.append(item)
        elif overwrite:
            update.append(item)
        else:
            skipped.append(f"{line_no}줄: 자산번호 {asset_no} 는 이미 있습니다 "
                           "(고치려면 아래 덮어쓰기를 켜세요)")

    return {"columns": list(columns), "new": new, "update": update, "skipped": skipped}


def apply_assets(db: Session, planned: dict) -> dict:
    existing = {a.asset_no: a for a in db.query(Asset).all() if a.asset_no}

    def fill(target, item):
        for key in ("label_no", "asset_type", "purchase_type", "manufacturer",
                    "model", "serial_no", "cpu", "os", "notes", "status"):
            value = item.get(key)
            if value not in (None, ""):
                setattr(target, key, value)
        if item["memory_gb"] is not None:
            target.memory_gb = item["memory_gb"]
        if item["storage_gb"] is not None:
            target.storage_gb = item["storage_gb"]

    def assign(target, item):
        """사용자가 적혀 있으면 지급 기록을 만든다.

        자산 대장의 축은 '누구에게 지급했나' 다. 사용자 칸을 그냥 버리면
        받아서 고쳐 올린 파일의 절반이 반영되지 않는다.
        """
        if not item["holder_id"]:
            return
        holder = uuid.UUID(item["holder_id"])
        current = (db.query(AssetAssignment)
                   .filter(AssetAssignment.asset_id == target.id,
                           AssetAssignment.returned_at.is_(None))
                   .first())
        if current and current.employee_id == holder:
            return
        now = datetime.now(timezone.utc)
        if current:
            current.returned_at = now
        db.add(AssetAssignment(id=uuid.uuid4(), asset_id=target.id,
                               employee_id=holder, assigned_at=now))
        target.status = "IN_USE"

    for item in planned["new"]:
        row = Asset(id=uuid.uuid4(), asset_no=item["asset_no"])
        fill(row, item)
        db.add(row)
        db.flush()          # id 가 있어야 지급 기록을 붙일 수 있다
        assign(row, item)

    for item in planned["update"]:
        row = existing.get(item["asset_no"])
        if not row:
            continue
        fill(row, item)
        assign(row, item)

    db.commit()
    return {"added": len(planned["new"]), "updated": len(planned["update"])}
