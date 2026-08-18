"""data 폴더에서 엑셀 파일을 찾아주는 공용 모듈.

원래는 각 스크립트가 파일명을 코드에 박아두고 있었다. 세 가지가 문제였다.

  1. 한글 파일명 (노트북렌탈.xlsx)
     Windows(CP949)와 리눅스 서버(UTF-8) 사이에서 깨진다.
     Docker 볼륨이나 git 에서도 말썽이 난다.

  2. 버전 번호가 박힌 파일명 (IT_SW_Userlist_v2.2_2607.xlsx)
     새 버전을 받으면 파일명이 바뀌고, 스크립트는 조용히 0건을 넣는다.

  3. 오타 (lisence.xlsx → license)

그래서 '정식 이름'을 정해두되, 예전 이름과 버전이 붙은 이름도 함께 찾는다.
파일명을 바꾸지 않아도 동작하고, 바꾸면 더 깔끔해진다.
"""

from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


# 이름: (정식 파일명, 이 파일을 찾을 때 쓸 패턴들, 설명)
# 패턴은 위에서부터 순서대로 시도한다.
FILE_SPECS = {
    "pc_list": (
        "pc_list.xlsx",
        ["pc_list.xlsx", "PC_list.xlsx", "PC대장*.xlsx", "pc*list*.xlsx"],
        "PC 자산 대장",
    ),
    "rental": (
        "rental.xlsx",
        ["rental.xlsx", "노트북렌탈.xlsx", "*rental*.xlsx", "*렌탈*.xlsx", "*임대*.xlsx"],
        "노트북 렌탈 계약",
    ),
    "license": (
        "license.xlsx",
        ["license.xlsx", "lisence.xlsx", "*license*.xlsx", "*lisence*.xlsx", "*라이선스*.xlsx"],
        "소프트웨어 라이선스",
    ),
    "layout": (
        "layout.xlsx",
        ["layout.xlsx", "layout_test.xlsx", "*배치도*.xlsx", "*layout*.xlsx", "*seat*.xlsx"],
        "사무실 좌석 배치도",
    ),
    "sw_userlist": (
        "sw_userlist.xlsx",
        ["sw_userlist.xlsx", "IT_SW_Userlist*.xlsx", "*SW*Userlist*.xlsx", "*sw*user*.xlsx"],
        "SW 사용현황 / IP 대역",
    ),
}


def find_data_file(key: str, required: bool = False) -> Path | None:
    """정식 이름 → 예전 이름 → 패턴 순으로 찾는다.

    required=True 인데 없으면 예외를 던진다.
    아니면 경고만 남기고 None 을 돌려준다 (호출한 쪽에서 건너뛰도록).
    """
    canonical, patterns, desc = FILE_SPECS[key]

    for pattern in patterns:
        if "*" in pattern:
            matches = sorted(DATA_DIR.glob(pattern))
            if matches:
                found = matches[-1]  # 여러 개면 이름순 마지막 = 보통 최신 버전
                if found.name != canonical:
                    print(f"  [안내] {desc}: '{found.name}' 사용 "
                          f"(권장 이름: {canonical})")
                return found
        else:
            candidate = DATA_DIR / pattern
            if candidate.exists():
                if pattern != canonical:
                    print(f"  [안내] {desc}: '{pattern}' 사용 "
                          f"(권장 이름: {canonical})")
                return candidate

    have = sorted(p.name for p in DATA_DIR.glob("*.xlsx")) if DATA_DIR.exists() else []
    message = (f"{desc} 파일을 찾을 수 없습니다. "
               f"data 폴더에 '{canonical}' 로 넣어주세요.\n"
               f"    현재 data 폴더: {', '.join(have) if have else '(비어있음)'}")
    if required:
        raise FileNotFoundError(message)
    print(f"  [경고] {message}")
    return None
