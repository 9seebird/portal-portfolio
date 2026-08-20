# -*- coding: utf-8 -*-
"""체험판에 넣을 가짜 자료를 전부 만든다.

    python3 tools/make_demo_data.py            없는 것만 만든다
    python3 tools/make_demo_data.py --force    있어도 다시 만든다

만들기만 한다. **앱 안에 넣는 것은 이 스크립트가 하지 않는다.**
넣는 일은 앱마다 자기 컨테이너 안에서 한다 (demo.sh 가 순서대로 부른다).

    it-asset          data/demo_seed.json      → scripts/seed_demo.py
    leave-anomaly     data/demo/*.xlsx         → app/seed_demo.py
    manual-import     data/demo/*.pptx         → app/seed_demo.py
    portal            data/demo_seed.json      → app/demo.py (뜰 때)
    ai-report         data/*.xlsx              (파일을 두면 목록에 뜬다)
    biz-plan          예제는 화면에 들어 있다

왜 이렇게 나눴나
────────────────
앱의 표 구조와 검사 규칙은 그 앱만 안다. 밖에서 DB 에 직접 쓰면
「그 앱의 업로드로는 통과 못 할 자료」가 화면에 앉게 되고, 그러면
데모에서만 되는 상태가 된다. 각 앱이 **자기 파서를 거쳐** 받아들이게
해 두면, 자료가 들어갔다는 사실 자체가 그 앱이 돈다는 확인이 된다.

────────────────────────────────────────────────────────────
여기서 나오는 회사 · 사람 · 금액은 전부 지어낸 것이다.
기준은 tools/demo_company.py 한 곳에 있다.
"""

import io
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

FORCE = "--force" in sys.argv


def say(msg: str) -> None:
    print("  " + msg)


def need(path: Path) -> bool:
    """이미 있으면 건드리지 않는다 (--force 면 다시 만든다)."""
    if path.exists() and not FORCE:
        say(f"· {path.relative_to(ROOT)} — 이미 있음")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    return True


def xlsx(rows: list[list], sheet: str = "Sheet1") -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def main() -> int:
    import demo_company as C
    print(f"▸ 가상 회사 「{C.COMPANY}」")

    # ── 자산관리 · 포털 계정 ────────────────────────────────
    # ★ 두 파일을 **따로** 확인한다.
    #   처음에는 자산 파일을 만들 때 안에서 포털 파일도 같이 썼다.
    #   그랬더니 자산 파일만 남아 있는 상태에서 다시 돌렸을 때
    #   포털 파일이 영영 안 만들어졌다 — 계정이 demo 하나뿐인 채로 뜨는데
    #   오류는 없어서, 관리자 화면을 열어 보고서야 알았다.
    import gen_asset_data
    asset_json = ROOT / "it-asset" / "data" / "demo_seed.json"
    portal_json = ROOT / "portal" / "data" / "demo_seed.json"
    edu_json = ROOT / "edu" / "data" / "demo_seed.json"

    # ★ or 로 잇지 않는다. `need(a) or need(b)` 는 a 가 참이면 b 를
    #   **아예 부르지 않는다**(단축 평가). need() 가 폴더를 만드는 일도
    #   같이 하므로, 그러면 portal/data 폴더가 안 생겨서 바로 아래에서
    #   FileNotFoundError 로 죽는다. 둘 다 먼저 부르고 나서 판단한다.
    want_asset = need(asset_json)
    want_portal = need(portal_json)
    want_edu = need(edu_json)

    data = gen_asset_data.build() if (want_asset or want_portal or want_edu) else None

    if want_asset:
        asset_json.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        say(f"✓ 자산 — 직원 {len(data['employees'])} · 자산 {len(data['assets'])} "
            f"· 라이선스 {len(data['license_assignments'])}")

    if want_portal:
        # 포털은 사람만 있으면 된다. 같은 명부를 쓰므로 챗에서
        # "한윤현 자산 뭐 써?" 가 실제로 답을 낸다.
        portal_json.write_text(json.dumps({"employees": data["employees"]},
                                          ensure_ascii=False), encoding="utf-8")
        say(f"✓ 포털 계정 — {len(data['employees'])}명")

    if want_edu:
        # 교육 앱도 사람만 있으면 된다. 같은 명부를 쓰므로 이수 현황에 뜨는
        # 이름이 자산·연차 화면의 그 사람과 같다.
        edu_json.write_text(json.dumps({"employees": data["employees"]},
                                       ensure_ascii=False), encoding="utf-8")
        say(f"✓ 교육 대상자 — {len(data['employees'])}명")

    # ── 연차 이상패턴 ───────────────────────────────────────
    import gen_leave_data
    lv = ROOT / "leave-anomaly" / "data" / "demo"
    if need(lv / "연차_사용내역.xlsx"):
        d = gen_leave_data.build()
        (lv / "연차_사용내역.xlsx").write_bytes(xlsx(d["usage"]))
        (lv / "연차_발생내역.xlsx").write_bytes(xlsx(d["accrual"]))
        (lv / "회사휴일.txt").write_text(
            "\n".join(f"{k}\t{v}" for k, v in d["holidays"]), encoding="utf-8")
        say(f"✓ 연차 — 사용 {len(d['usage']) - 1}건 · 발생 {len(d['accrual']) - 1}명")
        say("  심어 둔 것: " + " · ".join(f"{k} {v}" for k, v in d["planted"].items()))

    # ── AI 사용량 리포트 ────────────────────────────────────
    import gen_report_data
    ym = date.today().strftime("%Y-%m")
    rep = ROOT / "ai-report" / "data" / f"AI사용량_{ym}.xlsx"
    if need(rep):
        rows = gen_report_data.build()
        # 시트 이름이 stat 여야 한다. 화면이 「원본 로그」로 알아보는 표식이다.
        rep.write_bytes(xlsx(rows, sheet="stat"))
        say(f"✓ 리포트 — {len(rows) - 1}행 ({ym})")

    # ── 매뉴얼 PPT ──────────────────────────────────────────
    mi = ROOT / "manual-import" / "data" / "demo"
    if need(mi / "1. 샘플 ERP 접속 매뉴얼.pptx"):
        try:
            import gen_manual_ppt as M
            M.make_erp(str(mi / "1. 샘플 ERP 접속 매뉴얼.pptx"))
            M.make_groupware(str(mi / "2. 샘플 그룹웨어 사용 매뉴얼.pptx"))
            say("✓ 매뉴얼 — PPT 2개")
        except ImportError as e:
            say(f"! 매뉴얼 PPT 를 만들지 못했습니다 ({e}). "
                "python-pptx · Pillow 가 필요합니다.")

    # 매뉴얼 앱은 it-guide 폴더에 직접 쓴다. 폴더가 없으면 볼륨을 못 붙인다.
    for d in (ROOT / "it-guide" / "web" / "manuals" / "data",
              ROOT / "it-guide" / "web" / "manuals" / "images"):
        d.mkdir(parents=True, exist_ok=True)

    print("")
    print("  다음:  ./deploy.sh --no-pull   그리고 각 앱의 seed_demo")
    print("        (demo.sh 를 쓰면 여기까지 한 번에 됩니다)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
