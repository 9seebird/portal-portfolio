"""DB 통째로 옮기기 — 로컬(Postgres) → 서버(SQLite) 또는 그 반대.

왜 필요한가
-----------
웹에서 자산을 정리하기 시작하면 원본이 엑셀이 아니라 DB가 된다.
서버에 배포할 때 엑셀 임포트를 다시 돌리면 정리한 내용이 사라지므로,
대신 이 스크립트로 지금 DB 내용을 그대로 복사한다.

SQLAlchemy 모델을 통해 읽고 쓰기 때문에 Postgres↔SQLite 엔진이
서로 달라도 동작한다.

사용법
------
  # 예: 로컬 Postgres -> 서버로 가져갈 SQLite 파일
  python scripts/transfer_db.py ^
      --source "postgresql+psycopg://asset_user:비밀번호@127.0.0.1:5432/asset_portal" ^
      --dest   "sqlite+pysqlite:///./data/app.db" ^
      --yes

  --yes 없이 실행하면 건수만 보여주고 아무것도 바꾸지 않는다(dry-run).
  대상 DB의 기존 데이터는 전부 지워지고 원본 내용으로 대체된다.

주의
----
- 대상 DB에 테이블이 없으면 만들어준다 (alembic 없이도 동작).
- 옮긴 뒤에는 엑셀 임포트 스크립트를 다시 돌리지 말 것 — 정리 전 상태가 부활한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# 아래 import 는 SQLAlchemy 와 모델 11개를 전부 읽느라 몇 초 걸린다.
# 그동안 화면에 아무것도 안 나오면 멈춘 줄 알고 Ctrl+C 를 누르게 되므로 먼저 알린다.
print("준비 중... (모델 로딩, 5~15초)", flush=True)

from sqlalchemy import create_engine, insert, inspect, select

import app.models  # noqa: F401  (모델 등록)
from app.db.base import Base

print("준비 완료.", flush=True)

# FK 의존 순서대로. 부모 테이블을 먼저 넣어야 자식이 들어간다.
TABLE_ORDER = [
    "users",
    "employees",
    "assets",
    "software_products",
    "license_pools",
    "asset_assignments",
    "ip_ranges",
    "ip_assignments",
    "software_installations",
    "license_assignments",
    "seats",
    "rental_contracts",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="DB 내용을 다른 DB로 복사")
    parser.add_argument("--source", required=True, help="원본 DATABASE_URL")
    parser.add_argument("--dest", required=True, help="대상 DATABASE_URL")
    parser.add_argument("--yes", action="store_true",
                        help="실제로 복사한다 (없으면 dry-run)")
    args = parser.parse_args()

    if args.source == args.dest:
        sys.exit("[중단] 원본과 대상이 같습니다.")

    # SQLite 는 폴더가 없으면 "unable to open database file" 이라는
    # 원인을 알 수 없는 메시지만 낸다. 미리 확인해서 어디를 만들어야 하는지 알려준다.
    if args.dest.startswith("sqlite"):
        db_path = Path(args.dest.split(":///")[-1])
        parent = (db_path if db_path.is_absolute() else Path.cwd() / db_path).parent
        if not parent.exists():
            sys.exit(f"[중단] 대상 폴더가 없습니다: {parent}\n"
                     f"        mkdir 로 먼저 만드세요.")
        print(f"대상 파일 경로: {parent / db_path.name}")

    src = create_engine(args.source)
    dst = create_engine(args.dest)

    tables = Base.metadata.tables
    missing = [t for t in TABLE_ORDER if t not in tables]
    if missing:
        sys.exit(f"[중단] 모델에 없는 테이블: {missing} — TABLE_ORDER 를 갱신하세요.")
    unknown = sorted(set(tables) - set(TABLE_ORDER))
    if unknown:
        # 새 테이블이 생겼는데 여기 목록에 안 넣으면 조용히 누락된다. 그래서 막는다.
        sys.exit(f"[중단] TABLE_ORDER 에 없는 테이블 발견: {unknown} — 순서에 추가하세요.")

    # 대상에 테이블이 없으면 만든다.
    # dry-run 에서는 절대 만들지 않는다 — 스키마만 남고 alembic 버전 도장이 없는
    # 어중간한 DB 가 생겨서, 나중에 alembic upgrade head 가
    # "table users already exists" 로 실패한다.
    if args.yes:
        Base.metadata.create_all(dst)

    # 원본이 대상보다 오래된 스키마일 수 있다. 예를 들어 seats 는 SQLite 에만
    # 만들어 두고 Postgres 에는 없는 식이다. 그런 표는 건너뛴다 —
    # 여기서 죽으면 그 앞까지 옮긴 것도 다 되돌아간다.
    present = set(inspect(src).get_table_names())
    absent = [t for t in TABLE_ORDER if t not in present]

    print(f"원본: {args.source.split('@')[-1]}")
    print(f"대상: {args.dest.split('@')[-1]}")
    if absent:
        print(f"[안내] 원본에 없는 표는 건너뜁니다: {', '.join(absent)}")
    print()

    with src.connect() as s, dst.begin() as d:
        # 지우는 건 역순 (자식 먼저)
        if args.yes:
            for name in reversed(TABLE_ORDER):
                d.execute(tables[name].delete())

        total = 0
        for name in TABLE_ORDER:
            table = tables[name]
            if name in absent:
                print(f"  {name:24} {'-':>5}  (원본에 없음)")
                continue
            rows = [dict(r._mapping) for r in s.execute(select(table))]
            print(f"  {name:24} {len(rows):>5}건")
            total += len(rows)
            if args.yes and rows:
                d.execute(insert(table), rows)

        print(f"  {'합계':24} {total:>5}건")
        if not args.yes:
            d.rollback()
            print("\n>>> DRY-RUN: 실제 복사하려면 --yes")
        else:
            print("\n>>> 복사 완료. 대상 DB에서 확인:")
            print("    (서버에서) python -m pytest 또는 화면 접속")


if __name__ == "__main__":
    main()
