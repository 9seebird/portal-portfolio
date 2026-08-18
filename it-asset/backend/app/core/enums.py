"""자산/직원 상태값의 단일 출처.

지금까지 asset_type 과 status 는 그냥 문자열이었다.
DB 컬럼도 String 이고 스키마도 str 이라, API로 아무 값이나 넣을 수 있었다.
그래서 "PC" 와 "DESKTOP" 이 섞여 들어가면 프론트의 라벨 표에 없는 값이 되고
화면에는 영문 원문이 그대로 노출된다. 집계도 따로 잡힌다.

값을 여기 한 곳에 모아두고 Pydantic 이 검증하게 한다.
프론트(app.js)의 ASSET_TYPES / ASSET_STATUS 와 반드시 같은 값을 유지할 것.
"""

from enum import Enum


class AssetType(str, Enum):
    LAPTOP = "LAPTOP"        # 노트북
    DESKTOP = "DESKTOP"      # 데스크탑
    MONITOR = "MONITOR"      # 모니터
    SERVER = "SERVER"        # 서버
    NETWORK = "NETWORK"      # 네트워크 장비
    OTHER = "OTHER"          # 기타


class AssetStatus(str, Enum):
    IN_USE = "IN_USE"        # 사용 중
    STORAGE = "STORAGE"      # 보관
    REPAIR = "REPAIR"        # 수리
    DISPOSED = "DISPOSED"    # 폐기


class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"        # 재직
    INACTIVE = "INACTIVE"    # 퇴사
    LEAVE = "LEAVE"          # 휴직


# 화면 표시용 한글 라벨 (필요하면 API로 내려줘서 프론트와 공유할 수 있다)
ASSET_TYPE_LABELS = {
    AssetType.LAPTOP: "노트북",
    AssetType.DESKTOP: "데스크탑",
    AssetType.MONITOR: "모니터",
    AssetType.SERVER: "서버",
    AssetType.NETWORK: "네트워크 장비",
    AssetType.OTHER: "기타",
}

ASSET_STATUS_LABELS = {
    AssetStatus.IN_USE: "사용 중",
    AssetStatus.STORAGE: "보관",
    AssetStatus.REPAIR: "수리",
    AssetStatus.DISPOSED: "폐기",
}

EMPLOYEE_STATUS_LABELS = {
    EmployeeStatus.ACTIVE: "재직",
    EmployeeStatus.INACTIVE: "퇴사",
    EmployeeStatus.LEAVE: "휴직",
}


# 배치도에서 '직책자'로 표시할 직책 이름들.
#
# 엑셀 배치도에는 (●) 로 손수 찍어뒀지만 빠지거나 잘못 찍힌 곳이 있었다.
# 직책은 어차피 직원 명단에 있는 값이므로 그걸 보고 판단한다.
# 승진·보직 변경이 있으면 직원 정보만 고치면 배치도가 따라간다.
#
# 회사 호칭이 바뀌면 여기만 고치면 된다.
MANAGER_TITLES = (
    "팀장", "디렉터", "디렉타",
    "본부장", "실장", "센터장", "그룹장", "파트장", "지점장",
    "이사", "상무", "전무", "부사장", "사장", "부회장", "회장", "대표",
)


def is_manager_title(*values: str | None) -> bool:
    """직책·직급 문자열 중 하나라도 직책자 호칭을 담고 있으면 True.

    '팀장'뿐 아니라 '영업1팀장', '디자인 팀장' 같은 형태도 잡히도록
    정확히 같은지가 아니라 포함 여부를 본다.
    """
    for value in values:
        if not value:
            continue
        flat = str(value).replace(" ", "")
        if any(title in flat for title in MANAGER_TITLES):
            return True
    return False
