"""손상된 SQLite 파일에서 살릴 수 있는 것만 건져낸다.

"database disk image is malformed" 는 파일 전체가 못 쓰게 됐다는 뜻이 아니다.
망가진 페이지에 걸린 테이블만 못 읽고, 나머지는 멀쩡한 경우가 대부분이다.

이 스크립트는
  1. 테이블별로 몇 건을 읽을 수 있는지 세어 보고
  2. --out 을 주면 읽히는 행만 새 파일로 옮긴다.

통째로 읽다가 실패하면 rowid 를 하나씩 훑어서 살아 있는 행만 건진다.
느리지만 몇 천 건 규모에서는 금방 끝난다.

사용법
------
  # 얼마나 살아 있는지 확인만 (원본은 건드리지 않는다)
  python scripts/sqlite_rescue.py --file ..\\data\\app.db

  # 건져서 새 파일로
  python scripts/sqlite_rescue.py --file ..\\data\\app.db --out ..\\data\\rescued.db

주의
----
- 원본은 절대 수정하지 않는다(읽기 전용으로 연다).
- 건져낸 파일은 '읽힌 것만' 들어 있다. 빠진 게 있는지 화면에서 반드시 확인할 것.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def open_readonly(path: Path) -> sqlite3.Connection:
    # immutable=1 : 잠금·저널을 건드리지 않고 읽기만 한다.
    uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def table_names(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    try:
        rows = conn.execute(
            "select name, sql from sqlite_master "
            "where type='table' and name not like 'sqlite_%' order by name"
        ).fetchall()
        return [(n, s) for n, s in rows if s]
    except sqlite3.DatabaseError as error:
        sys.exit(f"[중단] 목차(sqlite_master)조차 읽지 못합니다: {error}\n"
                 "        이 파일에서 건질 수 있는 건 없습니다. 백업이나 원본에서 복구하세요.")


def read_rows(conn: sqlite3.Connection, table: str) -> tuple[list, int, bool]:
    """(살린 행, 잃은 행 수, 통째로_읽었는지)"""
    try:
        return conn.execute(f'select * from "{table}"').fetchall(), 0, True
    except sqlite3.DatabaseError:
        pass

    # 통째로 안 되면 한 행씩. 손상된 페이지에 걸린 행만 버린다.
    try:
        lo, hi = conn.execute(f'select min(rowid), max(rowid) from "{table}"').fetchone()
    except sqlite3.DatabaseError:
        # min/max 도 못 읽으면 범위를 모른다. 1번부터 훑되,
        # 한동안 아무것도 안 나오면 끝난 것으로 본다.
        lo, hi = 1, None

    saved, lost = [], 0
    if lo is None:
        return [], 0, False

    GAP_LIMIT = 5000        # 연속으로 이만큼 허탕이면 끝으로 본다
    HARD_LIMIT = 2_000_000  # 안전장치
    rowid, miss, pending_lost = lo, 0, 0
    while True:
        if hi is not None and rowid > hi:
            break
        if hi is None and (miss >= GAP_LIMIT or rowid > HARD_LIMIT):
            break
        try:
            row = conn.execute(
                f'select * from "{table}" where rowid=?', (rowid,)
            ).fetchone()
            if row is not None:
                saved.append(row)
                # 마지막 성공 이후의 실패만 '손실'로 친다.
                # 끝을 찾느라 헛도는 구간까지 세면 숫자가 겁나게 부풀려진다.
                lost += pending_lost
                pending_lost = miss = 0
            else:
                miss += 1
        except sqlite3.DatabaseError:
            pending_lost += 1
            miss += 1
        rowid += 1

    return saved, lost, False


def main() -> None:
    parser = argparse.ArgumentParser(description="손상된 SQLite 에서 건지기")
    parser.add_argument("--file", required=True, help="손상된 app.db 경로")
    parser.add_argument("--out", help="건져낸 내용을 저장할 새 파일 (없으면 확인만)")
    args = parser.parse_args()

    src_path = Path(args.file).resolve()
    if not src_path.exists():
        sys.exit(f"[중단] 파일이 없습니다: {src_path}")

    src = open_readonly(src_path)
    try:
        ok = None
        try:
            ok = src.execute("PRAGMA integrity_check").fetchone()[0]
        except sqlite3.DatabaseError as error:
            ok = f"실패 ({error})"
        print(f"대상: {src_path}")
        print(f"무결성 검사: {ok}\n")

        tables = table_names(src)
        dst = None
        if args.out:
            out_path = Path(args.out).resolve()
            if out_path.exists():
                sys.exit(f"[중단] 이미 있는 파일입니다: {out_path}")
            dst = sqlite3.connect(out_path)

        total_saved = total_lost = 0
        for name, ddl in tables:
            saved, lost, clean = read_rows(src, name)
            total_saved += len(saved)
            total_lost += lost
            mark = "" if clean else ("  <- 일부만 건짐" if lost else "  <- 한 행씩 읽음")
            print(f"  {name:24} {len(saved):>6}건 살림" +
                  (f" / {lost}건 손실" if lost else "") + mark)

            if dst and saved:
                dst.execute(ddl)
                placeholders = ",".join("?" * len(saved[0]))
                dst.executemany(f'insert into "{name}" values ({placeholders})', saved)
            elif dst:
                dst.execute(ddl)

        print(f"\n  합계 {total_saved}건 살림" + (f", {total_lost}건 손실" if total_lost else ""))

        if dst:
            dst.commit()
            dst.close()
            print(f"\n>>> 저장: {out_path}")
            print("    화면에서 직원 수·자산 수가 맞는지 반드시 확인하세요.")
        else:
            print("\n>>> 확인만 했습니다. 건지려면 --out 경로를 주세요.")
    finally:
        src.close()


if __name__ == "__main__":
    main()
