"""체험판용 가짜 매뉴얼을 넣는다.

    docker compose exec -T manual-import python -m app.seed_demo

`/data/demo/*.pptx` 를 **화면에서 올린 것과 똑같은 길로** 집어넣는다.
같은 파서(pptx_parse)를 거치고 같은 함수(manuals_io)로 저장된다.

manuals.js 를 손으로 써 두지 않는 이유가 이것이다. 손으로 쓰면
「파서로는 못 만드는 결과」가 화면에 앉아 있게 되고, 파서가 망가져도
데모는 멀쩡해 보인다. 파서를 거치게 해 두면 이 매뉴얼이 보인다는 것
자체가 **파서가 돈다는 확인**이 된다.

이미 매뉴얼이 있으면 아무 일도 하지 않는다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import manuals_io as mio
from .pptx_parse import parse

# 컨테이너 안에서는 늘 이 자리다. 밖에서 시험할 때만 바꾼다.
DEMO_DIR = Path(os.environ.get("DEMO_DIR", "/data/demo"))

# 파일 이름 → 매뉴얼 ID. ID 는 주소에 쓰이므로 영문 소문자로 고정한다.
IDS = {
    "1": "sample-erp",
    "2": "sample-groupware",
}


def main() -> int:
    force = "--force" in sys.argv
    if not DEMO_DIR.exists():
        print(f"  {DEMO_DIR} 가 없습니다. 건너뜁니다.")
        return 0

    have = mio.list_manuals()
    if have and not force:
        print(f"  이미 매뉴얼 {len(have)}개가 있습니다. 그대로 둡니다.")
        return 0

    for path in sorted(DEMO_DIR.glob("*.pptx")):
        mid = IDS.get(path.name[:1], path.stem.lower().replace(" ", "-")[:32])
        blob = path.read_bytes()
        parsed = parse(blob)
        if not parsed["sections"]:
            print(f"  ✗ {path.name} — 글자를 찾지 못했습니다")
            continue
        n_img = mio.write_images(mid, parsed["sections"])
        mio.upsert(mid, parsed["title"] or mid, "", "",
                   parsed["sections"], parsed.get("contactNote") or "")
        mio.save_source(mid, path.name, blob)
        print(f"  ✓ {mid} — 항목 {len(parsed['sections'])}개 · 그림 {n_img}장 "
              f"· {parsed['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
