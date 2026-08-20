"""체험판용 가짜 교육 자료를 넣는다.

    docker exec -i demo-edu python -m app.seed_demo

**앱의 자기 함수를 거쳐서** 넣는다. DB 에 직접 쓰지 않는 이유가 있다.
직접 쓰면 「화면에서는 만들 수 없는 상태」가 앉게 되고, 그러면 판정 로직이
망가져도 체험판은 멀쩡해 보인다. 진도는 실제 재생을 흉내 내어 record_watch 를
반복 호출해서 쌓는다. 그래서 이 자료가 보인다는 것 자체가
**칸 채우기·이수 판정이 돌고 있다는 확인**이 된다.

사람은 지어내지 않는다. `/data/demo_seed.json` (tools/make_demo_data.py 가
만드는 가상 회사 명부)을 그대로 읽는다. 다른 앱과 같은 사람을 봐야
「자산관리에는 있는데 교육에는 없는 사람」이 생기지 않는다.

이미 자료가 있으면 아무 일도 하지 않는다. --force 를 주면 지우고 다시 넣는다.
"""

from __future__ import annotations

import contextlib
import json
import os
import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from . import db

SEED = 20260814          # 고정. 다시 돌려도 같은 화면이 나와야 스크린샷을 다시 찍을 수 있다.
SEED_FILE = Path(os.environ.get("DEMO_SEED", "/data/demo_seed.json"))

# 체험 계정도 명단에 넣는다. 없으면 방문자가 영상을 보는 순간
# 현황에 「명단 밖」으로 뜨는데, 처음 보는 사람에게는 오류처럼 보인다.
DEMO_ACCOUNT = {"id": "demo", "name": "체험 계정", "dept": "인사총무팀", "emp_no": "", "active": 1}

# 바깥 유튜브 영상이다. 게시자가 내리면 재생이 안 되므로, 그때는
# 담당자 화면에서 차시 [수정] 으로 다른 주소를 넣으면 된다.
LESSONS_BASIC = [
    {"title": "바이브코딩 입문 Vol.1 — 무엇이 달라지나",
     "kind": "youtube", "url": "https://www.youtube.com/watch?v=iRrfzddtuio",
     "note": "1.5배속으로 봐도 진도는 정상 기록됩니다", "duration": 714},
    {"title": "바이브코딩 입문 Vol.2 — 실제로 만들어 보기",
     "kind": "youtube", "url": "https://www.youtube.com/watch?v=6_dxWznoFps",
     "note": "가장 긴 차시입니다. 나눠 보셔도 이어서 재생됩니다", "duration": 2072},
]


@contextlib.contextmanager
def _one_transaction():
    """씨앗을 넣는 동안만 연결 하나를 돌려 쓴다.

    앱의 함수들은 호출마다 `with db.connect() as conn:` 으로 연결을 새로 연다.
    평소에는 그게 맞다 — 요청이 짧고 서로 얽히지 않는다. 그런데 씨앗은
    진도 기록을 수천 번 부르므로, 그 방식이면 커밋도 수천 번이 된다.
    윈도우의 바인드 마운트에서는 그게 몇 분씩 걸리고, 중간에 끊기면
    **자료가 반만 들어간 상태**가 된다(실제로 그렇게 됐다).

    그래서 db.connect 를 잠깐 갈아 끼워 같은 연결을 내주고, 커밋은 끝에
    한 번만 한다. **판정 로직은 그대로 지나간다** — 바꾸는 것은 연결을
    여닫는 부분뿐이다.
    """
    conn = sqlite3.connect(db.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    class Shared:
        """`with` 로 들어오면 같은 연결을 주고, 나갈 때 커밋하지 않는다."""
        def __enter__(self):
            return conn

        def __exit__(self, *exc):
            return False

        def __getattr__(self, name):
            return getattr(conn, name)

    real = db.connect
    db.connect = lambda: Shared()
    try:
        yield
        conn.commit()
    finally:
        db.connect = real
        conn.close()


def _people() -> list[dict]:
    """가상 회사 명부를 읽어 교육 대상자 모양으로 바꾼다."""
    if not SEED_FILE.exists():
        print(f"  ! {SEED_FILE} 가 없습니다. tools/make_demo_data.py 를 먼저 돌리세요.")
        return []
    data = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    out = []
    for p in data.get("employees", []):
        uid = (p.get("email") or "").split("@")[0] or p.get("emp_no")
        if not uid:
            continue
        out.append({
            "id": uid,
            "emp_no": p.get("emp_no") or "",
            "name": p.get("name") or "",
            "dept": p.get("department") or "",
            "active": 0 if p.get("status") and p["status"] != "ACTIVE" else 1,
        })
    return out


SAMPLE_PDF_TEXT = [
    "Vibe Coding Tool - Internal Quick Guide (sample)",
    "",
    "1. Open the portal and click [Prompt Builder].",
    "2. Fill in what you want to build. Keep it one sentence.",
    "3. Company coding rules are attached automatically.",
    "4. Copy the result into the AI tool and run it.",
    "5. Bring the finished zip to the IT desk for review.",
    "",
    "This is placeholder content for the demo.",
]


def _sample_pdf() -> bytes:
    """자료 차시를 보여 주려고 만드는 1쪽짜리 PDF.

    바깥 꾸러미를 쓰지 않고 직접 짠다. 체험판에 파일 하나를 놓기 위해
    reportlab 을 받아 오는 것은 무게가 맞지 않는다. 한글을 쓰려면 글꼴을
    끼워 넣어야 해서 본문은 영문으로 둔다 — 자리 채우기용 문서다.
    """
    lines = "".join(
        f"BT /F1 {14 if i == 0 else 11} Tf 60 {760 - i * 26} Td "
        f"({t.replace('(', '').replace(')', '')}) Tj ET\n"
        for i, t in enumerate(SAMPLE_PDF_TEXT))
    content = lines.encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n"
            f"{xref}\n%%EOF\n").encode()
    return bytes(out)


def _watch(user: dict, lesson: dict, upto_sec: int, step: int = 20) -> None:
    """실제 재생을 흉내 내어 진도를 쌓는다.

    화면은 5초마다 현재 위치를 보내온다. 여기서는 20초씩 보낸다 — 건너뛰기로
    보지 않는 한계(MAX_SEEK_GAP_SEC=30) 안이라 이어 본 것으로 인정된다.
    """
    dur = int(lesson["duration_sec"])
    prev = 0.0
    pos = float(step)
    while pos <= min(upto_sec, dur):
        db.record_watch(user, lesson, prev, pos, dur)
        prev, pos = pos, pos + step
    if prev < min(upto_sec, dur):
        db.record_watch(user, lesson, prev, float(min(upto_sec, dur)), dur)


def main() -> int:
    db.init_db()
    force = "--force" in sys.argv

    if db.list_courses() and not force:
        print("  이미 교육 자료가 있어 건너뜁니다.")
        return 0
    with _one_transaction():
        return _fill(force)


def _fill(force: bool) -> int:
    if force:
        for c in db.list_courses():
            db.delete_course(int(c["id"]))

    people = _people()
    if not people:
        return 1
    people.append(DEMO_ACCOUNT)
    db.replace_roster(people, source="file")
    print(f"  대상자 {len(people)}명")

    today = date.today()
    rnd = random.Random(SEED)

    # ── 과정 1 — 진행 중인 전사 교육 ─────────────────────────
    c1 = db.create_course(
        "2026 사내 바이브코딩 기초",
        "AI 로 업무 도구를 직접 만드는 방법을 익히는 과정입니다.\n"
        "영상 두 편을 보고, 사내 툴 사용법 자료까지 확인하면 이수 처리됩니다.",
        (today + timedelta(days=100)).isoformat(), 1)
    lessons1 = []
    for spec in LESSONS_BASIC:
        lid = db.create_lesson(c1, {
            "title": spec["title"], "kind": spec["kind"], "url": spec["url"],
            "youtube_id": spec["url"].split("v=")[-1], "note": spec["note"],
            "duration_sec": spec["duration"], "required": 1})
        lessons1.append(db.get_lesson(lid))

    # 자료 차시 — 업로드된 PDF 를 보여 주는 쪽
    pdf_name = "vibe-coding-tool-guide-sample.pdf"
    (db.UPLOAD_DIR / pdf_name).write_bytes(_sample_pdf())
    doc_id = db.create_lesson(c1, {
        "title": "사내 바이브코딩 툴 사용법 (자료)", "kind": "doc",
        "url": f"files/{pdf_name}",
        "note": "영상이 아니라 자료입니다. 다 보시면 아래 버튼을 눌러 주세요.",
        "required": 1})
    doc_lesson = db.get_lesson(doc_id)
    print(f"  과정 1 — 차시 {len(lessons1) + 1}개")

    # ── 과정 2 — 마감이 가까운 의무 교육 ────────────────────
    c2 = db.create_course(
        "개인정보보호 교육 (연 1회 의무)",
        "개인정보를 다루는 모든 직원이 연 1회 들어야 하는 교육입니다.",
        (today + timedelta(days=12)).isoformat(), 1)
    l2 = db.get_lesson(db.create_lesson(c2, {
        "title": "개인정보보호 기본 — 무엇이 개인정보인가",
        "kind": "youtube", "url": "https://www.youtube.com/watch?v=iRrfzddtuio",
        "youtube_id": "iRrfzddtuio", "note": "", "duration_sec": 714,
        "min_ratio": 0.8, "required": 1}))
    print("  과정 2 — 차시 1개")

    # ── 진도 ────────────────────────────────────────────────
    #
    # 화면이 그림이 나오려면 세 부류가 다 있어야 한다.
    #   다 들은 사람 / 듣다 만 사람 / 손도 안 댄 사람
    # 부서마다 이수율이 다르게 갈리도록 부서 순서로 비율을 조금씩 낮춘다.
    active = [p for p in people if p["active"] and p["id"] != "demo"]
    rnd.shuffle(active)

    done1 = active[:26]                  # 과정 1 이수
    partial1 = active[26:40]             # 과정 1 듣는 중
    for p in done1:
        who = {"id": p["id"], "name": p["name"], "dept": p["dept"]}
        for l in lessons1:
            _watch(who, l, int(l["duration_sec"]))
        db.mark_done(who, doc_lesson)
    for p in partial1:
        who = {"id": p["id"], "name": p["name"], "dept": p["dept"]}
        # 첫 차시는 다 보고 둘째 차시를 보는 중, 또는 첫 차시를 보는 중
        if rnd.random() < 0.5:
            _watch(who, lessons1[0], int(lessons1[0]["duration_sec"]))
            _watch(who, lessons1[1], int(lessons1[1]["duration_sec"] * rnd.uniform(0.1, 0.6)))
        else:
            _watch(who, lessons1[0], int(lessons1[0]["duration_sec"] * rnd.uniform(0.2, 0.8)))
        if rnd.random() < 0.4:
            db.mark_done(who, doc_lesson)
    print(f"  과정 1 진도 — 이수 {len(done1)} · 듣는 중 {len(partial1)} · "
          f"미시작 {len(active) - len(done1) - len(partial1)}")

    # 과정 2 는 마감이 가까워 대부분 끝냈다
    done2 = active[:44]
    for p in done2:
        who = {"id": p["id"], "name": p["name"], "dept": p["dept"]}
        _watch(who, l2, int(l2["duration_sec"]))
    print(f"  과정 2 진도 — 이수 {len(done2)} · 남은 사람 {len(active) - len(done2)}")

    # 체험 계정은 「막 시작한 사람」으로 둔다. 들어가서 이어보기를 바로 볼 수 있게.
    demo_who = {"id": "demo", "name": "체험 계정", "dept": "인사총무팀"}
    _watch(demo_who, lessons1[0], 180)
    print("  체험 계정 — 첫 차시 3분까지 (이어보기 확인용)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
