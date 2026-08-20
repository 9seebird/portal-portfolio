# -*- coding: utf-8 -*-
"""깃허브 워크플로 파일을 push 전에 검사한다.

    python3 tools/check_workflow.py

────────────────────────────────────────────────────────────
왜 필요한가

이 저장소는 워크플로 파일 때문에 **두 번** 헛돌았다. 둘 다 문법 오류가
아니라서 로컬 yaml 검사로는 잡히지 않았고, 깃허브에 올려 봐야 알았다.

  1. job ID 를 한글로 적었다
     → 「실행된 작업이 없습니다」로 끝나고 실패 메일만 왔다.
       깃허브의 job ID 는 영문·숫자·-·_ 만 된다. 화면 이름(name:)은 한글도 된다.

  2. 주석에 이중 중괄호를 예시로 적었다
     → "An expression was expected" 로 **파일 전체가 거부**됐다.
       깃허브는 run 블록 안의 주석까지 표현식으로 먼저 읽는다.
       하필 「이걸 쓰지 말라」고 경고하는 주석이 원인이었다.

둘 다 「올려 보기 전엔 모른다」가 문제였다. 그래서 push 앞에 세웠다
(.githooks/pre-push 가 부른다).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF_DIR = ROOT / ".github" / "workflows"

JOB_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
EXPR = re.compile(r"\$\{\{(.*?)\}\}", re.S)


def main() -> int:
    if not WF_DIR.is_dir():
        print("  워크플로 폴더가 없습니다. 건너뜁니다.")
        return 0

    try:
        import yaml
    except ImportError:
        print("  △ PyYAML 이 없어 워크플로 검사를 건너뜁니다  (pip install pyyaml)")
        return 0

    bad: list[str] = []
    files = sorted(list(WF_DIR.glob("*.yml")) + list(WF_DIR.glob("*.yaml")))
    if not files:
        print("  검사할 워크플로가 없습니다.")
        return 0

    for f in files:
        rel = f.relative_to(ROOT)
        text = f.read_text(encoding="utf-8")

        # ── 1. YAML 로 읽히는가 ──
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError as e:
            bad.append(f"  ✗ {rel}: YAML 을 읽지 못했습니다 — {e}")
            continue

        # ── 2. job ID 가 영문인가 ──
        for jid in (doc or {}).get("jobs", {}):
            if not JOB_ID.match(str(jid)):
                bad.append(
                    f"  ✗ {rel}: job ID 「{jid}」 는 쓸 수 없습니다.\n"
                    f"      영문·숫자·-·_ 만 됩니다. 한글은 name: 에 적으세요.")

        # ── 3. 이중 중괄호가 성한가 ──
        #   빈 것 · 짝이 안 맞는 것 · 중첩된 것을 본다. 셋 다 파일 전체를
        #   거부당하는 원인이고, 셋 다 YAML 로는 멀쩡해 보인다.
        for i, line in enumerate(text.splitlines(), 1):
            if line.count("${{") != line.count("}}"):
                bad.append(f"  ✗ {rel}:{i}: 이중 중괄호의 짝이 맞지 않습니다\n"
                           f"      {line.strip()}")
                continue
            for m in EXPR.finditer(line):
                inner = m.group(1).strip()
                if not inner:
                    bad.append(
                        f"  ✗ {rel}:{i}: 안이 빈 이중 중괄호가 있습니다.\n"
                        f"      깃허브가 표현식으로 읽어 파일 전체를 거부합니다.\n"
                        f"      (주석 안이라도 마찬가지입니다)\n"
                        f"      {line.strip()}")
                elif "${{" in inner:
                    bad.append(f"  ✗ {rel}:{i}: 이중 중괄호가 중첩됐습니다\n"
                               f"      {line.strip()}")

    if bad:
        print("\n".join(bad))
        return 1
    print(f"  ✓ 워크플로 {len(files)}개 정상 (job ID · 표현식)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
