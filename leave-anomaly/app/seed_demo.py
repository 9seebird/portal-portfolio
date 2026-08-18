"""체험판용 가짜 연차 자료를 넣는다.

    docker compose exec -T leave-anomaly python -m app.seed_demo

`/data/demo/` 에 놓인 엑셀 두 개(사용내역 · 발생내역)를 **직원이 화면에서
올린 것과 똑같은 길로** 집어넣는다. 파서를 거치고, 같은 검사를 받고,
같은 함수로 저장된다.

DB 에 직접 쓰지 않는 이유가 이것이다. 직접 쓰면 「업로드로는 통과 못 할
자료」가 화면에 앉아 있게 되고, 그러면 데모에서만 되는 상태가 된다.
파서를 거치게 해 두면, 이 자료가 들어갔다는 사실 자체가 **파서가
멀쩡히 돈다는 확인**이 된다.

이미 자료가 있으면 아무 일도 하지 않는다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import db
from .parsers import normalize_accrual, normalize_usage, read_table

# 컨테이너 안에서는 늘 이 자리다. 밖에서 시험할 때만 바꾼다.
DEMO_DIR = Path(os.environ.get("DEMO_DIR", "/data/demo"))
WHO = {"id": "demo", "name": "체험 계정", "dept": "인사총무팀"}

FILES = {
    "usage": "연차_사용내역.xlsx",
    "accrual": "연차_발생내역.xlsx",
}

HOLIDAYS_FILE = DEMO_DIR / "회사휴일.txt"   # 한 줄에  YYYY-MM-DD<탭>이름


def main() -> int:
    db.init_db()
    force = "--force" in sys.argv

    if not DEMO_DIR.exists():
        print(f"  {DEMO_DIR} 가 없습니다. 건너뜁니다.")
        return 0

    for kind, name in FILES.items():
        if db.get_dataset(kind) and not force:
            print(f"  {kind} — 이미 있습니다. 그대로 둡니다.")
            continue
        path = DEMO_DIR / name
        if not path.exists():
            print(f"  ✗ {path} 가 없습니다.")
            continue
        blob = path.read_bytes()
        rows = read_table(blob, name)
        parsed = normalize_usage(rows) if kind == "usage" else normalize_accrual(rows)

        # 올린 파일을 보관하는 자리에 사본을 둔다. 화면에서 「원본 받기」를
        # 눌렀을 때 줄 파일이 여기 없으면 링크가 깨진다.
        stored = db.UPLOAD_DIR / f"{kind}-demo-{name}"
        stored.write_bytes(blob)
        db.save_dataset(kind, name, str(stored), parsed, WHO)
        print(f"  ✓ {kind} — {name} · {len(parsed)}건")

    if HOLIDAYS_FILE.exists():
        for line in HOLIDAYS_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            key, _, label = line.partition("\t")
            db.upsert_company_holiday(key.strip(), label.strip() or "회사휴일", WHO)
        print("  ✓ 회사휴일")
    return 0


if __name__ == "__main__":
    sys.exit(main())
