"""내선번호 자료를 명령줄에서 넣는다.

화면(내선 관리 → 자료 넣기)에서 파일을 올리는 게 더 편하다. 이 스크립트는
자료가 아주 많거나 서버에서 한꺼번에 돌릴 때 쓴다.
읽는 규칙은 화면과 완전히 같다 (app/services/extension_import.py 를 함께 쓴다).

  내선번호 | 이름   | IP            (있으면 좋은 것: 부서, 구역, 메모, 사번)
  ---------|--------|--------------
  1234     | 정예호 | 10.10.100.11
  1235     | 한윤현 | 10.10.100.12
  1236     |        |                <- 비워두면 '빈 번호'로 들어간다

  # 뭐가 들어갈지 먼저 보기 (아무것도 안 바꾼다)
  python scripts/import_extensions.py --file data/내선번호.xlsx

  # 실제로 넣기
  python scripts/import_extensions.py --file data/내선번호.xlsx --yes

이미 있는 번호는 건너뛴다. 덮어쓰려면 --overwrite 를 붙인다.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.database import SessionLocal  # noqa: E402
from app.services import extension_import  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="내선번호 가져오기")
    parser.add_argument("--file", required=True, help="엑셀(.xlsx) 또는 CSV 경로")
    parser.add_argument("--yes", action="store_true", help="실제로 넣는다. 없으면 미리보기만.")
    parser.add_argument("--overwrite", action="store_true",
                        help="이미 있는 번호도 파일 내용으로 덮어쓴다.")
    args = parser.parse_args()

    path = Path(args.file).expanduser()
    if not path.exists():
        sys.exit(f"[중단] 파일이 없습니다: {path}")

    db = SessionLocal()
    try:
        try:
            rows = extension_import.read_table(path.read_bytes(), path.name)
            planned = extension_import.plan(db, rows, overwrite=args.overwrite)
        except extension_import.ImportError_ as error:
            sys.exit(f"[중단] {error}")

        with_people = sum(1 for i in planned["new"] if i["employee_id"])
        with_ip = sum(1 for i in planned["new"] if i["ip"])

        print()
        print(f"  파일     : {path}")
        print(f"  찾은 칸  : {', '.join(planned['columns'])}")
        print(f"  새로 넣기: {len(planned['new'])}개"
              f" (사람 붙는 것 {with_people}개, IP 붙는 것 {with_ip}개)")
        if args.overwrite:
            print(f"  덮어쓰기 : {len(planned['update'])}개")
        print(f"  건너뜀   : {len(planned['skipped'])}개")
        for line in planned["skipped"][:15]:
            print(f"      - {line}")
        if len(planned["skipped"]) > 15:
            print(f"      … 그리고 {len(planned['skipped']) - 15}개 더")

        for item in planned["new"][:5]:
            who = item["employee_name"] or "(빈 번호)"
            ip = f" · {item['ip']}" if item["ip"] else ""
            print(f"      예: {item['number']} → {who}{ip}")
        print()

        if not args.yes:
            print("미리보기입니다. 실제로 넣으려면 --yes 를 붙이세요.")
            return

        counts = extension_import.apply_plan(db, planned)
        print(f"끝났습니다. 새로 {counts['added']}개"
              + (f", 덮어쓴 것 {counts['updated']}개" if args.overwrite else "")
              + ". 화면에서 새로고침하세요.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
