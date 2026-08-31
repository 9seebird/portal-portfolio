"""엑셀 배치도 → seats 테이블.

엑셀에서 한 칸(또는 병합된 여러 칸)이 곧 배치도의 한 블록이다.

  "재무팀\\n오도현(●)"  → DESK  team=재무팀, label=오도현, marked=True
  "회의실"              → ROOM
  "재무팀"              → LABEL (구역 표시 글자)

층은 'OO층' 이 적힌 제목 행을 기준으로 나눈다.

사용법
------
  python scripts/import_layout.py                 # 미리보기 (아무것도 안 바꿈)
  python scripts/import_layout.py --yes           # 적용
  python scripts/import_layout.py --yes --people-only
        배치는 그대로 두고 앉은 사람만 엑셀 기준으로 다시 맞춘다.
  python scripts/import_layout.py --yes --add-empty
        지금 DB에 없는 칸(주로 빈 책상)만 더한다. 기존 배치와 사람은 그대로.

주의
----
웹에서 자리를 정리하기 시작한 뒤에는 --yes 로 전체 재적재를 하지 말 것.
사람만 맞추려면 --people-only 를 쓴다.
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

print("준비 중... (모델 로딩, 5~15초)", flush=True)

from app.db.database import SessionLocal
from app.models.employee import Employee
from app.models.seat import Seat
from scripts.datafiles import find_data_file

print("준비 완료.", flush=True)

# 사람이 앉지 않는 공간을 알아보는 단어들.
ROOM_WORDS = (
    "회의실", "미팅룸", "탕비실", "창고", "출입구", "계단", "통신실",
    "주차", "택배", "프린트", "진열장", "공용", "업무용PC", "재단",
    "임원", "CEO", "부회장", "본부장",
)

# 이름 뒤에 붙는 직함. 직원 표와 대조할 때 떼어낸다.
NAME_SUFFIXES = ("기사", "비서", "사원", "대리", "과장", "차장", "부장", "팀장")

MAX_COL = 19  # A~S. 그 오른쪽은 도형·메모 영역이라 무시한다.

# 엑셀(xlsx)은 그냥 zip 안의 XML이다. 이 저장소의 다른 임포트 스크립트도
# 같은 방식으로 읽는다. openpyxl 을 쓰지 않는 이유는 배포 이미지에
# 가끔 한 번 쓰는 라이브러리를 넣지 않기 위해서다.
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"a": MAIN_NS}


def col_index(cell_ref: str) -> int:
    """'C4' -> 3 (1부터)."""
    letters = re.match(r"[A-Z]+", cell_ref).group(0)
    value = 0
    for ch in letters:
        value = value * 26 + ord(ch) - 64
    return value


def sheet_path(target: str) -> str:
    """workbook.xml.rels 의 Target 을 zip 안의 실제 경로로 바꾼다.

    엑셀을 만든 프로그램에 따라 "worksheets/sheet1.xml" 이기도 하고
    "/xl/worksheets/sheet1.xml" 처럼 절대경로이기도 하다.
    앞의 것만 가정하면 KeyError 로 죽는다.
    """
    import posixpath
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join("xl", target))


def read_sheet(path: Path) -> tuple[dict, list, set]:
    """첫 시트를 (셀값, 병합범위, 테두리로 그린 빈 칸) 으로 읽는다.

    셀값: {(행, 열): "텍스트"}   — 줄바꿈 그대로 보존
    병합: [(첫행, 첫열, 끝행, 끝열), ...]
    빈 칸: 글자는 없는데 사방이 테두리로 둘러진 칸 = 사람이 없는 책상

    배치도에서 아직 아무도 안 앉은 책상은 네모만 그려져 있다.
    글자가 있는 칸만 읽으면 그 책상이 통째로 사라져서, 신규 입사자를
    앉힐 자리가 화면에 없게 된다.
    """
    with ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for si in root.findall("a:si", NS):
                # 서식이 섞이면 <t> 가 여러 개로 쪼개진다. 이어 붙여야 원문이 된다.
                shared.append("".join(t.text or "" for t in si.iter(f"{{{MAIN_NS}}}t")))

        # 어떤 서식이 사방 테두리인지 미리 정리해 둔다.
        boxed_styles: set[int] = set()
        if "xl/styles.xml" in archive.namelist():
            styles = ET.fromstring(archive.read("xl/styles.xml"))
            border_defs = styles.find("a:borders", NS)
            boxed_borders = set()
            if border_defs is not None:
                for index, border in enumerate(border_defs):
                    drawn = sum(
                        1 for side in ("left", "right", "top", "bottom")
                        if (node := border.find(f"a:{side}", NS)) is not None
                        and node.get("style")
                    )
                    if drawn >= 4:
                        boxed_borders.add(index)
            cell_xfs = styles.find("a:cellXfs", NS)
            if cell_xfs is not None:
                for index, xf in enumerate(cell_xfs):
                    if int(xf.get("borderId", "0")) in boxed_borders:
                        boxed_styles.add(index)

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
        first = workbook.find("a:sheets", NS)[0]
        target = sheet_path(relmap[first.attrib[f"{{{REL_NS}}}id"]])

        sheet = ET.fromstring(archive.read(target))

    cells: dict[tuple[int, int], str] = {}
    boxes: set[tuple[int, int]] = set()
    for row in sheet.findall(".//a:sheetData/a:row", NS):
        r = int(row.attrib["r"])
        for cell in row.findall("a:c", NS):
            c = col_index(cell.attrib["r"])
            kind = cell.attrib.get("t")
            if kind == "inlineStr":
                node = cell.find("a:is", NS)
                text = "".join(t.text or "" for t in node.iter(f"{{{MAIN_NS}}}t")) if node is not None else ""
            else:
                node = cell.find("a:v", NS)
                text = node.text or "" if node is not None else ""
                if kind == "s" and text:
                    text = shared[int(text)]
            if text and text.strip():
                cells[(r, c)] = text
            elif int(cell.get("s", "0")) in boxed_styles:
                boxes.add((r, c))

    merges = []
    for node in sheet.findall(".//a:mergeCells/a:mergeCell", NS):
        start, _, end = node.attrib["ref"].partition(":")
        r0, c0 = int(re.search(r"\d+", start).group()), col_index(start)
        if end:
            r1, c1 = int(re.search(r"\d+", end).group()), col_index(end)
        else:
            r1, c1 = r0, c0
        merges.append((r0, c0, r1, c1))

    return cells, merges, boxes


def parse_blocks(path: Path) -> list[dict]:
    cells, merges, boxes = read_sheet(path)
    if not cells:
        sys.exit("[중단] 시트에서 읽어낸 칸이 없습니다. 파일을 확인하세요.")

    merged: dict[tuple[int, int], tuple[int, int]] = {}
    covered: set[tuple[int, int]] = set()
    for r0, c0, r1, c1 in merges:
        merged[(r0, c0)] = (r1 - r0 + 1, c1 - c0 + 1)
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                if (r, c) != (r0, c0):
                    covered.add((r, c))

    max_row = max(r for r, _ in cells)

    # 'OO층' 이 적힌 행을 찾아 층 경계를 잡는다.
    # 시트 구조가 바뀌어도 제목만 있으면 따라간다.
    titles: list[tuple[int, str]] = []
    for r in range(1, max_row + 1):
        for c in range(1, MAX_COL + 1):
            v = cells.get((r, c))
            if v and (m := re.search(r"(\d+)\s*층", v)):
                titles.append((r, f"{m.group(1)}층"))
                break
    if not titles:
        sys.exit("[중단] 'OO층' 이라고 적힌 제목 칸을 찾지 못했습니다. 시트를 확인하세요.")

    bounds = []
    for i, (row, floor) in enumerate(titles):
        end = titles[i + 1][0] - 1 if i + 1 < len(titles) else max_row
        bounds.append((floor, row + 1, end))

    blocks: list[dict] = []
    for floor, r0, r1 in bounds:
        for r in range(r0, r1 + 1):
            for c in range(1, MAX_COL + 1):
                if (r, c) in covered:
                    continue
                raw = cells.get((r, c))
                if raw is None or not raw.strip():
                    # 글자는 없지만 네모가 그려져 있으면 '아무도 없는 책상'이다.
                    if (r, c) in boxes:
                        row_span, col_span = merged.get((r, c), (1, 1))
                        blocks.append(
                            dict(floor=floor, row_idx=r - r0 + 1, col_idx=c,
                                 row_span=row_span, col_span=col_span,
                                 kind="DESK", team=None, label=None, marked=False)
                        )
                    continue
                text = raw.strip()
                row_span, col_span = merged.get((r, c), (1, 1))

                team = None
                marked = False
                if "\n" in text:
                    head, tail = (p.strip() for p in text.split("\n", 1))
                    flat_tail = tail.replace(" ", "")
                    if any(w in flat_tail for w in ROOM_WORDS):
                        # "미르\n통신실" 처럼 두 줄이지만 사람이 아닌 것
                        kind, label = "ROOM", tail
                    else:
                        marked = "●" in tail
                        label = tail.replace("(●)", "").replace("●", "").strip()
                        kind, team = "DESK", head
                else:
                    flat = text.replace(" ", "")
                    kind = "ROOM" if any(w in flat for w in ROOM_WORDS) else "LABEL"
                    label = re.sub(r"\s+", " ", text)

                blocks.append(
                    dict(floor=floor, row_idx=r - r0 + 1, col_idx=c,
                         row_span=row_span, col_span=col_span,
                         kind=kind, team=team, label=label, marked=marked)
                )
    return blocks


def build_name_index(db) -> dict[str, list[Employee]]:
    index: dict[str, list[Employee]] = {}
    for emp in db.query(Employee).all():
        if emp.name:
            index.setdefault(emp.name.replace(" ", ""), []).append(emp)
    return index


def match_employee(label: str, index: dict[str, list[Employee]]):
    """엑셀에 적힌 이름 → 직원.

    배치도에는 자리가 좁아서 줄여 적는 경우가 있다.
      "가브리엘 소피아"(직원표) 를 배치도에는 "소피아" 로만 써두는 식.
    그래서 정확히 일치 → 직함 떼고 일치 → 부분 일치 순으로 찾는다.
    부분 일치는 후보가 딱 하나일 때만 인정한다. 둘 이상이면 사람이 판단해야 한다.
    """
    candidates = [label.replace(" ", "")]
    for suffix in NAME_SUFFIXES:
        if candidates[0].endswith(suffix):
            candidates.append(candidates[0][: -len(suffix)])

    for key in candidates:
        found = index.get(key)
        if found and len(found) == 1:
            return found[0], None
        if found:
            return None, f"동명이인 {len(found)}명"

    # 부분 일치. 두 글자 미만은 우연히 겹치기 쉬워서 시도하지 않는다.
    for key in candidates:
        if len(key) < 2:
            continue
        hits = [emp for name, emps in index.items() if key in name for emp in emps]
        unique = {emp.id: emp for emp in hits}
        if len(unique) == 1:
            emp = next(iter(unique.values()))
            return emp, f"부분 일치: {emp.name}"
        if len(unique) > 1:
            names = ", ".join(sorted(e.name for e in unique.values())[:3])
            return None, f"비슷한 이름 {len(unique)}명 ({names}…)"

    return None, "직원표에 없음"


def main() -> None:
    parser = argparse.ArgumentParser(description="엑셀 배치도를 seats 테이블로")
    parser.add_argument("--file", help="엑셀 경로 (없으면 data 폴더에서 찾음)")
    parser.add_argument("--yes", action="store_true", help="실제로 적용")
    parser.add_argument("--people-only", action="store_true",
                        help="배치는 두고 앉은 사람만 갱신")
    parser.add_argument("--add-empty", action="store_true",
                        help="지금 DB에 없는 칸만 추가한다 (기존 배치·사람은 손대지 않음)")
    args = parser.parse_args()

    path = Path(args.file) if args.file else find_data_file("layout", required=True)
    blocks = parse_blocks(path)

    kinds: dict[str, int] = {}
    for b in blocks:
        kinds[b["kind"]] = kinds.get(b["kind"], 0) + 1
    print(f"\n엑셀: {path.name}")
    print(f"  블록 {len(blocks)}개 — " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    floors = sorted({b["floor"] for b in blocks})
    for f in floors:
        rows = [b for b in blocks if b["floor"] == f]
        desks = [b for b in rows if b["kind"] == "DESK"]
        empty = [b for b in desks if not b["label"]]
        print(f"  {f}: 전체 {len(rows)}칸, 자리 {len(desks)}개"
              + (f" (이름 없는 빈 책상 {len(empty)}개)" if empty else ""))

    db = SessionLocal()
    try:
        index = build_name_index(db)
        matched, unmatched, fuzzy = 0, [], []
        for b in blocks:
            if b["kind"] != "DESK":
                continue
            if not b["label"]:
                b["employee_id"] = None      # 엑셀에도 비어 있던 책상
                continue
            emp, reason = match_employee(b["label"], index)
            b["employee_id"] = emp.id if emp else None
            if emp:
                matched += 1
                if reason:  # 부분 일치 — 맞는지 사람이 한 번 봐야 한다
                    fuzzy.append((b["floor"], b["label"], reason))
            else:
                unmatched.append((b["floor"], b["label"], reason))

        desk_total = sum(1 for b in blocks if b["kind"] == "DESK" and b["label"])
        print(f"\n직원 연결: {matched}/{desk_total}")
        if fuzzy:
            print(f"  [확인] 이름이 정확히 같지 않아 추측으로 붙인 {len(fuzzy)}명 —"
                  " 화면에서 맞는지 봐주세요.")
            for floor, label, reason in fuzzy:
                print(f"    {floor}  {label:12} → {reason}")
        if unmatched:
            print(f"  [안내] 연결 못 한 {len(unmatched)}명 — 화면에서 직접 지정하면 됩니다.")
            for floor, label, reason in unmatched:
                print(f"    {floor}  {label:12} ({reason})")

        # 같은 사람이 두 자리에 적혀 있으면 DB 제약에 걸린다. 먼저 잡아준다.
        seen: dict = {}
        for b in blocks:
            eid = b.get("employee_id")
            if not eid:
                continue
            if eid in seen:
                print(f"  [경고] {b['label']} 이(가) 두 곳에 있습니다 "
                      f"({seen[eid]}, {b['floor']} {b['row_idx']}행). 뒤엣것은 비워둡니다.")
                b["employee_id"] = None
            else:
                seen[eid] = f"{b['floor']} {b['row_idx']}행"

        if not args.yes:
            print("\n>>> 미리보기입니다. 적용하려면 --yes")
            return

        if args.add_empty:
            existing = {
                (seat.floor, seat.row_idx, seat.col_idx)
                for seat in db.query(Seat.floor, Seat.row_idx, Seat.col_idx).all()
            }
            added = 0
            for b in blocks:
                if (b["floor"], b["row_idx"], b["col_idx"]) in existing:
                    continue
                db.add(Seat(
                    floor=b["floor"], row_idx=b["row_idx"], col_idx=b["col_idx"],
                    row_span=b["row_span"], col_span=b["col_span"],
                    kind=b["kind"], label=b["label"], team=b["team"],
                    marked=b["marked"], employee_id=b.get("employee_id"),
                ))
                added += 1
            db.commit()
            print(f"\n>>> 없던 칸 {added}개 추가. 기존 배치와 사람은 그대로입니다.")
            return

        if args.people_only:
            updated = 0
            for b in blocks:
                if b["kind"] != "DESK":
                    continue
                seat = (
                    db.query(Seat)
                    .filter(Seat.floor == b["floor"],
                            Seat.row_idx == b["row_idx"],
                            Seat.col_idx == b["col_idx"])
                    .first()
                )
                if seat and seat.employee_id != b["employee_id"]:
                    seat.employee_id = b["employee_id"]
                    updated += 1
            db.commit()
            print(f"\n>>> 사람만 갱신: {updated}칸 변경")
            return

        existing = db.query(Seat).count()
        if existing:
            print(f"\n기존 {existing}칸을 지우고 새로 넣습니다.")
        db.query(Seat).delete()
        for b in blocks:
            db.add(Seat(
                floor=b["floor"], row_idx=b["row_idx"], col_idx=b["col_idx"],
                row_span=b["row_span"], col_span=b["col_span"],
                kind=b["kind"], label=b["label"], team=b["team"],
                marked=b["marked"], employee_id=b.get("employee_id"),
            ))
        db.commit()
        print(f"\n>>> 완료: {len(blocks)}칸 저장")
    finally:
        db.close()


if __name__ == "__main__":
    main()
