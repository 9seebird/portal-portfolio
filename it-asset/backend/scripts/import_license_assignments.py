"""SW 리스트(사람별 소프트웨어 보유 현황) → license_assignments 이관.

sw_userlist.xlsx 의 'SW 리스트' 시트에는 사람별로 어떤 소프트웨어를
쓰는지가 O 표시로 기록되어 있다. 이걸 license_assignments 로 옮겨야
"지금 누가 무엇을 쓰는지"가 화면에서 관리 가능해진다.

처리 원칙 (2026-07-28 결정):
  - 직원 테이블에 있는 이름만 이관한다.
    장비/공용 PC 행(MSDS 전용PC, 기기(...), 택배송장...)과
    PC대장에 없는 사람(박주은, 이혜연 — 퇴사 미처리 추정)은
    직원이 아니므로 자동으로 걸러지고, 결과 보고서에 표시된다.
  - 장비 PC 의 소프트웨어는 자산 쪽(software_installations)에 이미 있으므로
    여기서 다루지 않는다.
  - 이관 일자는 알 수 없으므로 assigned_at 은 비워두고 note 로 출처를 남긴다.

기본은 dry-run 이다. 실제 반영은 --apply.
(import_licenses_ip.py 와 같은 방식)
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import func

from app.db.database import SessionLocal
from app.models.employee import Employee
from app.models.license_assignment import LicenseAssignment
from app.models.license_pool import LicensePool
from app.models.software_product import SoftwareProduct
from scripts.datafiles import find_data_file
from scripts.import_licenses_ip import SW_TO_LICENSE, load_sheet

SHEET = "SW 리스트"
NAME_HEADER = "성명"


def find_columns(rows: list[list[str]]) -> tuple[int, int, dict[int, str]]:
    """헤더를 내용으로 찾는다.

    행 번호를 박아두지 않는다 — 시트 위쪽에 제목/병합 행이 몇 줄 있는지는
    파일 버전마다 달라질 수 있다. '성명' 이 있는 행에서 이름 열을,
    SW_TO_LICENSE 의 컬럼명이 가장 많이 모여 있는 행에서 SW 열들을 찾는다.
    """
    name_row = name_col = -1
    for i, row in enumerate(rows[:10]):
        cells = [str(c or "").strip() for c in row]
        if NAME_HEADER in cells:
            name_row, name_col = i, cells.index(NAME_HEADER)
            break
    if name_row < 0:
        raise SystemExit(f"[중단] '{SHEET}' 시트에서 '{NAME_HEADER}' 헤더를 찾지 못했습니다.")

    best_row, sw_cols = -1, {}
    for i, row in enumerate(rows[:10]):
        cells = [str(c or "").strip() for c in row]
        found = {j: c for j, c in enumerate(cells) if c in SW_TO_LICENSE}
        if len(found) > len(sw_cols):
            best_row, sw_cols = i, found
    if not sw_cols:
        raise SystemExit(
            f"[중단] SW 컬럼({', '.join(SW_TO_LICENSE)})을 한 개도 찾지 못했습니다."
        )

    data_start = max(name_row, best_row) + 1
    return data_start, name_col, sw_cols


def main() -> None:
    apply = "--apply" in sys.argv

    rows = load_sheet(find_data_file("sw_userlist", required=True), SHEET)
    data_start, name_col, sw_cols = find_columns(rows)
    print(f"  헤더 인식: 이름 {name_col + 1}열, SW 컬럼 {len(sw_cols)}개, "
          f"데이터 {data_start + 1}행부터")

    db = SessionLocal()
    try:
        # 이름 → 직원. 동명이인은 어느 쪽인지 알 수 없으므로 건너뛰고 보고한다.
        name_counts: dict[str, int] = {}
        by_name: dict[str, Employee] = {}
        for emp in db.query(Employee).all():
            key = (emp.name or "").strip()
            name_counts[key] = name_counts.get(key, 0) + 1
            by_name[key] = emp
        duplicated = {n for n, c in name_counts.items() if c > 1}

        # 라이선스 품명 → 풀
        pool_by_name: dict[str, LicensePool] = {}
        for pool, product in (
            db.query(LicensePool, SoftwareProduct)
            .join(SoftwareProduct, SoftwareProduct.id == LicensePool.software_id)
            .all()
        ):
            pool_by_name[product.name] = pool

        granted = skipped_dup = already = 0
        not_employee: list[str] = []
        no_pool: set[str] = set()

        for row in rows[data_start:]:
            name = str(row[name_col] or "").strip() if name_col < len(row) else ""
            if not name or name in ("계", "합계") or name.isdigit():
                continue

            owned = [
                sw for col, sw in sw_cols.items()
                if col < len(row) and str(row[col] or "").strip()
            ]
            if not owned:
                continue

            if name in duplicated:
                print(f"  [경고] 동명이인 '{name}' — 어느 직원인지 알 수 없어 건너뜁니다.")
                skipped_dup += 1
                continue

            emp = by_name.get(name)
            if emp is None:
                not_employee.append(name)
                continue

            for sw in owned:
                license_name = SW_TO_LICENSE[sw]
                pool = pool_by_name.get(license_name)
                if pool is None:
                    no_pool.add(license_name)
                    continue

                exists = db.query(LicenseAssignment).filter(
                    LicenseAssignment.license_pool_id == pool.id,
                    LicenseAssignment.employee_id == emp.id,
                    LicenseAssignment.released_at.is_(None),
                ).first()
                if exists:
                    already += 1
                    continue

                db.add(LicenseAssignment(
                    license_pool_id=pool.id,
                    employee_id=emp.id,
                    note="SW 리스트 엑셀 이관",
                ))
                granted += 1

        print()
        print(f"부여 {granted}건 / 이미 있음 {already}건 / 동명이인 건너뜀 {skipped_dup}건")
        if not_employee:
            print(f"직원이 아니라 건너뜀 {len(not_employee)}건: {', '.join(not_employee)}")
            print("  (장비/공용 PC 는 자산으로 관리, 퇴사 미처리자는 이관 제외 — 결정사항)")
        if no_pool:
            print(f"[경고] 라이선스 풀이 없어 건너뜀: {', '.join(sorted(no_pool))}")
            print("  (import_licenses_ip.py --apply 를 먼저 실행했는지 확인)")

        if apply:
            db.commit()
            print("\n>>> DB에 반영했습니다.")
            print("\n=== 이관 후 실사용 현황 ===")
            for pool, product in (
                db.query(LicensePool, SoftwareProduct)
                .join(SoftwareProduct, SoftwareProduct.id == LicensePool.software_id)
                .all()
            ):
                used = db.query(func.count(LicenseAssignment.id)).filter(
                    LicenseAssignment.license_pool_id == pool.id,
                    LicenseAssignment.released_at.is_(None),
                ).scalar() or 0
                if used or pool.purchased_count:
                    have = pool.purchased_count
                    over = "  <-- 초과!" if (have is not None and used > have) else ""
                    print(f"  {product.name[:36]:38} 보유 {str(have):>4} / "
                          f"실사용 {used:>3}{over}")
        else:
            db.rollback()
            print("\n>>> DRY-RUN: 반영하려면 --apply")
    finally:
        db.close()


if __name__ == "__main__":
    main()
