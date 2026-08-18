"""SQLite 파일을 도커(바인드 마운트)에서 열 수 있는 상태로 만든다.

왜 필요한가
-----------
WAL 모드는 본체(app.db) 말고도 app.db-wal, app.db-shm 두 파일을 함께 쓴다.
-shm 은 메모리 매핑이 되어야 하는데, Docker Desktop(Windows/macOS)의
바인드 마운트는 그걸 제대로 지원하지 않는다. 그 상태로 컨테이너가 열면

    sqlite3.DatabaseError: database disk image is malformed

이 뜬다. 파일이 진짜로 깨진 게 아니라 열지 못하는 것이다.

이 스크립트는
  1. 무결성을 먼저 확인하고
  2. WAL 에 남아 있는 내용을 본체로 합친 뒤(checkpoint)
  3. 저널 모드를 DELETE 로 내려서 -wal / -shm 을 없앤다.

실행 전에 컨테이너와 로컬 uvicorn 을 모두 내려서
아무도 그 파일을 잡고 있지 않게 하세요.

사용법
------
  python scripts/sqlite_prepare.py                       # data/app.db
  python scripts/sqlite_prepare.py --file 경로\\app.db
  python scripts/sqlite_prepare.py --mode WAL            # 리눅스 서버에서 되돌릴 때
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = BACKEND_ROOT.parent / "data" / "app.db"


def main() -> None:
    parser = argparse.ArgumentParser(description="SQLite 저널 모드 정리")
    parser.add_argument("--file", default=str(DEFAULT_DB), help="app.db 경로")
    parser.add_argument("--mode", default="DELETE", choices=["DELETE", "WAL", "TRUNCATE"],
                        help="바꿀 저널 모드 (기본 DELETE)")
    parser.add_argument("--no-backup", action="store_true", help="백업 사본을 만들지 않는다")
    args = parser.parse_args()

    path = Path(args.file).resolve()
    if not path.exists():
        sys.exit(f"[중단] 파일이 없습니다: {path}")

    print(f"대상: {path}")
    for suffix in ("-wal", "-shm"):
        side = Path(str(path) + suffix)
        if side.exists():
            print(f"  곁다리 파일: {side.name} ({side.stat().st_size:,} 바이트)")

    if not args.no_backup:
        backup = path.with_name(path.stem + "_before_prepare" + path.suffix)
        shutil.copy2(path, backup)
        print(f"  백업 생성: {backup.name}")

    conn = sqlite3.connect(path)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        print(f"  무결성 검사: {result}")
        if result != "ok":
            sys.exit("[중단] 파일이 실제로 손상되었습니다. 백업본에서 복구하세요.")

        before = conn.execute("PRAGMA journal_mode").fetchone()[0]
        print(f"  현재 모드: {before}")

        # WAL 에 남은 내용을 본체로 합친다. 이걸 건너뛰고 -wal 을 지우면
        # 최근 변경분이 사라진다.
        if before.lower() == "wal":
            busy, logged, checkpointed = conn.execute(
                "PRAGMA wal_checkpoint(TRUNCATE)"
            ).fetchone()
            print(f"  WAL 병합: {checkpointed}/{logged} 페이지 반영 (busy={busy})")

        after = conn.execute(f"PRAGMA journal_mode={args.mode}").fetchone()[0]
        print(f"  바뀐 모드: {after}")

        rows = conn.execute(
            "select count(*) from sqlite_master where type='table'"
        ).fetchone()[0]
        print(f"  테이블 {rows}개 확인")
    finally:
        conn.close()

    leftovers = [Path(str(path) + s) for s in ("-wal", "-shm")]
    remaining = [p.name for p in leftovers if p.exists()]
    print(f"\n남은 곁다리 파일: {remaining or '없음'}")
    print(">>> 이제 docker compose up -d 로 올리면 됩니다.")


if __name__ == "__main__":
    main()
