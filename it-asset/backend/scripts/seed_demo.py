"""체험판용 가짜 데이터를 넣는다.

    docker compose exec -T api python scripts/seed_demo.py

이 스크립트는 **아무것도 지어내지 않는다.** `/app/data/demo_seed.json` 을
읽어 그대로 넣기만 한다. 무엇을 넣을지는 저장소 루트의
`tools/gen_asset_data.py` 가 정한다.

왜 둘로 나눴나
──────────────
표의 모양(모델)은 이 앱만 안다. 그런데 「누가 어느 팀이고 누가 무엇을
쓰는가」는 다른 앱들과 맞아야 한다 — 챗에서 "한윤현 자산 뭐 써?" 를
물으면 포털 계정 · 자산 · 휴가가 같은 사람을 가리켜야 하기 때문이다.

그래서 이야기는 바깥에서 만들고, 여기서는 넣기만 한다.
사이를 오가는 것은 JSON 파일 하나라 서로의 사정을 몰라도 된다.

이미 데이터가 있으면 **아무 일도 하지 않는다.** 덮어쓰면 방문자가
만들어 둔 화면이 배포 한 번에 사라지고, 무엇보다 실수로 사내 DB 에
돌렸을 때 되돌릴 수 없다.  --force 를 붙여야만 지우고 다시 넣는다.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.base import Base                      # noqa: E402
from app.db.database import SessionLocal, engine  # noqa: E402
from app.models import (Asset, AssetAssignment, Employee, Extension,  # noqa: E402
                        IPAssignment, IPRange, LicenseAssignment, LicensePool,
                        RentalContract, Seat, SoftwareInstallation,
                        SoftwareProduct)

# 컨테이너 안에서는 늘 이 자리다 (compose 가 ./data 를 /app/data 로 붙인다).
# 밖에서 시험할 때만 DEMO_SEED_FILE 로 바꾼다.
SEED_FILE = Path(os.environ.get("DEMO_SEED_FILE", "/app/data/demo_seed.json"))
FORCE = "--force" in sys.argv

# 지우는 순서가 중요하다. 남을 참조하는 쪽부터 지운다.
# 반대로 하면 외래키 제약에 걸려 중간에 멈추고, 반쯤 지워진 DB 가 남는다.
WIPE_ORDER = [IPAssignment, LicenseAssignment, SoftwareInstallation,
              AssetAssignment, RentalContract, Seat, Extension,
              LicensePool, SoftwareProduct, IPRange, Asset, Employee]


# ★ 단계마다 db.flush() 를 부른다.
#
#   한 번에 다 넣고 마지막에 commit 하면 "FOREIGN KEY constraint failed" 로
#   죽는다. SQLAlchemy 가 넣는 순서를 스스로 정하는데, 이 앱의 표들은
#   relationship() 없이 ForeignKey 만으로 이어져 있어서 참조되는 쪽이
#   늘 먼저 들어간다는 보장이 없다.
#
#   flush 는 「지금까지 만든 것을 DB 로 밀어 넣되 commit 은 하지 않는다」다.
#   그래서 실패하면 여전히 통째로 되돌아가고(rollback), 순서만 확실해진다.


def d(v):
    return date.fromisoformat(v) if v else None


def main() -> int:
    if not SEED_FILE.exists():
        print(f"✗ {SEED_FILE} 가 없습니다. 먼저 tools/make_demo_data.py 를 돌리세요.")
        return 1

    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        have = db.query(Employee).count()
        if have and not FORCE:
            print(f"  이미 직원 {have}명이 들어 있습니다. 그대로 둡니다.")
            print("  (지우고 다시 넣으려면  python scripts/seed_demo.py --force )")
            return 0
        if have:
            print(f"  --force — 기존 데이터를 지웁니다 (직원 {have}명)")
            for model in WIPE_ORDER:
                db.query(model).delete()
            db.commit()

        raw = json.loads(SEED_FILE.read_text(encoding="utf-8"))

        # ── 직원 ────────────────────────────────────────────
        emp: dict[str, uuid.UUID] = {}
        for p in raw["employees"]:
            e = Employee(
                id=uuid.uuid4(), emp_no=p["emp_no"], name=p["name"],
                company=p.get("company"), location=p.get("location"),
                department=p["department"], position=p.get("position"),
                rank=p.get("rank"), email=p.get("email"), phone=p.get("phone"),
                hire_date=d(p.get("hire_date")),
                resign_date=d(p.get("resign_date")),
                status=p.get("status", "ACTIVE"),
            )
            db.add(e)
            emp[p["emp_no"]] = e.id
        db.flush()   # ★ 아래 참고

        # ── 자산 ────────────────────────────────────────────
        ast: dict[str, uuid.UUID] = {}
        for a in raw["assets"]:
            x = Asset(
                id=uuid.uuid4(), asset_no=a["asset_no"], label_no=a.get("label_no"),
                source_key=a["asset_no"], asset_type=a["asset_type"],
                manufacturer=a.get("manufacturer"), model=a.get("model"),
                serial_no=a.get("serial_no"), cpu=a.get("cpu"),
                memory_gb=a.get("memory_gb"), storage_gb=a.get("storage_gb"),
                os=a.get("os"), purchase_type=a.get("purchase_type"),
                purchase_date=d(a.get("purchase_date")),
                rental_vendor=a.get("rental_vendor"),
                rental_end_date=d(a.get("rental_end_date")),
                status=a.get("status", "STORAGE"), notes=a.get("notes"),
            )
            db.add(x)
            ast[a["asset_no"]] = x.id
        db.flush()

        for g in raw["asset_assignments"]:
            db.add(AssetAssignment(
                id=uuid.uuid4(), asset_id=ast[g["asset_no"]],
                employee_id=emp[g["emp_no"]],
                assigned_at=datetime.fromisoformat(g["assigned_at"]).replace(
                    tzinfo=timezone.utc)))

        for c in raw["rental_contracts"]:
            db.add(RentalContract(
                id=uuid.uuid4(), asset_id=ast[c["asset_no"]], vendor=c["vendor"],
                contract_no=c.get("contract_no"), start_date=d(c.get("start_date")),
                end_date=d(c.get("end_date")), monthly_fee=c.get("monthly_fee"),
                status=c.get("status", "ACTIVE")))

        # ── 자리 ────────────────────────────────────────────
        for s in raw["seats"]:
            db.add(Seat(
                id=uuid.uuid4(), floor=s["floor"], row_idx=s["row_idx"],
                col_idx=s["col_idx"], row_span=s.get("row_span", 1),
                col_span=s.get("col_span", 1), kind=s.get("kind", "DESK"),
                label=s.get("label"), team=s.get("team"),
                employee_id=emp.get(s.get("emp_no") or "")))

        # ── 내선 ────────────────────────────────────────────
        ext: dict[str, uuid.UUID] = {}
        for e2 in raw["extensions"]:
            x = Extension(
                id=uuid.uuid4(), number=e2["number"],
                employee_id=emp.get(e2.get("emp_no") or ""),
                zone=e2.get("zone"), note=e2.get("note"))
            db.add(x)
            ext[e2["number"]] = x.id
        db.flush()

        # ── IP ──────────────────────────────────────────────
        rng: dict[str, uuid.UUID] = {}
        for g in raw["ip_ranges"]:
            x = IPRange(id=uuid.uuid4(), name=g["name"], kind=g.get("kind", "NETWORK"),
                        start_ip=g["start_ip"], end_ip=g["end_ip"], vlan=g.get("vlan"),
                        gateway=g.get("gateway"), dns=g.get("dns"),
                        description=g.get("description"))
            db.add(x)
            rng[g["name"]] = x.id
        db.flush()

        for g in raw["ip_assignments"]:
            db.add(IPAssignment(
                id=uuid.uuid4(), kind=g.get("kind", "NETWORK"),
                ip_range_id=rng.get(g.get("range") or ""),
                asset_id=ast.get(g.get("asset_no") or ""),
                extension_id=ext.get(g.get("ext_number") or ""),
                ip_address=g["ip_address"], hostname=g.get("hostname"),
                mac_address=g.get("mac_address"), status=g.get("status", "USED")))

        # ── 소프트웨어 ──────────────────────────────────────
        sw: dict[str, uuid.UUID] = {}
        for g in raw["software_products"]:
            x = SoftwareProduct(id=uuid.uuid4(), name=g["name"], vendor=g.get("vendor"),
                                license_type=g.get("license_type"),
                                description=g.get("description"))
            db.add(x)
            sw[g["name"]] = x.id
        db.flush()

        pool: dict[str, uuid.UUID] = {}
        for g in raw["license_pools"]:
            x = LicensePool(id=uuid.uuid4(), software_id=sw[g["software"]],
                            purchased_count=g.get("purchased_count"),
                            used_count=0, expire_date=d(g.get("expire_date")),
                            alert_days=g.get("alert_days", 30))
            db.add(x)
            pool[g["software"]] = x.id
        db.flush()

        used: dict[str, int] = {}
        for g in raw["license_assignments"]:
            db.add(LicenseAssignment(
                id=uuid.uuid4(), license_pool_id=pool[g["software"]],
                employee_id=emp[g["emp_no"]], assigned_at=d(g.get("assigned_at")),
                note=g.get("note")))
            used[g["software"]] = used.get(g["software"], 0) + 1

        # ★ 쓰는 수(used_count)를 부여 건수로 맞춰 둔다.
        #   0 으로 두면 소프트웨어 화면에는 「4개 사서 0개 씀」이 뜨는데,
        #   바로 옆 사용현황 화면은 표를 세어 「6개 씀」이라고 한다.
        #   한 화면 안에서 두 숫자가 어긋나 보이는 것이 제일 나쁘다.
        for name, cnt in used.items():
            db.get(LicensePool, pool[name]).used_count = cnt

        for g in raw["software_installations"]:
            db.add(SoftwareInstallation(
                id=uuid.uuid4(), software_id=sw[g["software"]],
                asset_id=ast[g["asset_no"]], installed_at=d(g.get("installed_at"))))

        db.commit()
        print(f"  ✓ 직원 {len(raw['employees'])} · 자산 {len(raw['assets'])} "
              f"· 자리 {len(raw['seats'])} · 내선 {len(raw['extensions'])} "
              f"· IP {len(raw['ip_assignments'])} "
              f"· 라이선스 {len(raw['license_assignments'])}")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
