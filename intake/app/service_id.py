"""서비스 ID(앱이 붙을 주소) 가 쓸 수 있는 모양인지 본다.

이 파일이 따로 있는 이유 —
  같은 판정을 세 곳이 쓴다. 제출을 받을 때, 입력 중에 화면이 물어볼 때,
  중복을 확인할 때. 한 곳에 두지 않으면 셋이 조금씩 달라지고,
  "화면에서는 되는데 올리면 안 된다" 가 된다.
"""

from __future__ import annotations

import re

SERVICE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")


def suggest_service_id(raw: str) -> str:
    """사람이 적은 것을 주소로 쓸 수 있는 모양으로 바꿔 본다."""
    v = (raw or "").strip().lower()
    v = re.sub(r"[\s_.]+", "-", v)        # 공백·밑줄·점 → 붙임표
    v = re.sub(r"[^a-z0-9-]", "", v)      # 나머지 쓸 수 없는 글자는 버린다
    v = re.sub(r"-{2,}", "-", v).strip("-")
    v = re.sub(r"^[0-9]+", "", v).strip("-")   # 숫자로 시작할 수 없다
    return v[:31]


def check_service_id(raw: str) -> tuple[str, str]:
    """(고친 값, 안 되는 이유) 를 돌려준다. 이유가 비어 있으면 통과다.

    "규칙에 맞지 않습니다" 로 끝내면 받는 사람은 무엇을 고쳐야 할지 모른다.
    주소에 쓸 수 없는 글자라는 것을 모르는 사람이 대부분이라, 무엇이 걸렸는지와
    **바꿔 쓸 값**을 같이 알려 준다.
    """
    v = (raw or "").strip()
    if not v:
        return "", "서비스 ID 를 입력해 주세요."

    fixed = suggest_service_id(v)
    tail = f" — 「{fixed}」 로 쓰시면 됩니다." if fixed and fixed != v.lower() else ""

    if "_" in v:
        return v, f"밑줄(_)은 인터넷 주소에 쓸 수 없습니다. 붙임표(-)로 바꿔 주세요{tail}"
    if " " in v:
        return v, f"띄어쓰기는 주소에 쓸 수 없습니다. 붙임표(-)로 이어 주세요{tail}"
    if any("가" <= ch <= "힣" for ch in v):
        return v, f"한글은 주소에 쓸 수 없습니다. 영문으로 적어 주세요{tail}"
    if v != v.lower():
        return v, f"대문자는 쓰지 않습니다. 소문자로 적어 주세요{tail}"
    if v[0].isdigit():
        return v, f"숫자로 시작할 수 없습니다. 영문자로 시작해 주세요{tail}"
    if len(v) < 2:
        return v, "두 글자 이상이어야 합니다."
    if len(v) > 31:
        return v, "31글자까지만 쓸 수 있습니다. 더 짧게 줄여 주세요."
    if not SERVICE_ID_RE.match(v):
        bad = sorted({ch for ch in v if not re.match(r"[a-z0-9-]", ch)})
        chars = " ".join(f"({c})" for c in bad) if bad else ""
        return v, (f"주소에 쓸 수 없는 글자가 있습니다 {chars}. "
                   f"영문 소문자·숫자·붙임표만 씁니다{tail}")
    return v, ""
