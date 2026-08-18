"""감지 기준(임계값) 한 곳 모음. 기준을 바꾸려면 이 파일만 고치면 된다.

원본 Team Planner(oz.js)의 ANOMALY_CONFIG 값을 그대로 옮겨온 것이다.
"""

ANOMALY_CONFIG = {
    # 이상 패턴을 보는 관찰 창(일)
    "windowDays": 21,
    # 가중치 = 휴가 유형 × 요일(월=1 … 금=5)
    "weights": {
        "fullAnnual": {1: 0.25, 2: 1.0, 3: 1.0, 4: 1.0, 5: 0.5},
        "halfAM": {1: 0.5, 2: 1.25, 3: 1.25, 4: 1.25, 5: 1.5},
        "quarterAM": {1: 0.25, 2: 0.5, 3: 0.5, 4: 0.5, 5: 0.25},
        "eighthAM": {1: 0.0, 2: 0.25, 3: 0.25, 4: 0.25, 5: 0.0},
        "halfPM": {1: 1.5, 2: 1.5, 3: 1.5, 4: 1.5, 5: 0.75},
        "quarterPM": {1: 1.5, 2: 1.5, 3: 1.5, 4: 1.5, 5: 0.5},
        "eighthPM": {1: 0.25, 2: 0.25, 3: 0.25, 4: 0.25, 5: 0.25},
    },
    "tiers": {
        # 위험 = 점수 3.0 이상 AND 고립 3회 이상
        "danger": {"minScore": 3.0, "minCount": 3, "label": "위험"},
        # 검토 = 점수 2.5 이상 OR 고립 3회 이상
        "review": {"minScore": 2.5, "minCount": 3, "label": "검토"},
        # 관찰 = 점수 2.0 이상
        "observe": {"minScore": 2.0, "label": "관찰"},
    },
    # 전 직원의 50% 이상이 쉬는 날은 집단연차로 보고 고립 판정에서 제외
    "massLeaveRatio": 0.5,
    # 저사용(연차 쌓아두기) 기준
    "lowUsage": {"gapPoint": 25, "minAccrued": 10, "yearDays": 365},
    # 급증(몰아쓰기) 기준
    "spike": {"windowDays": 60, "minRecentDays": 3, "ratio": 2.5},
}

# 업로드 허용 기준
ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB

# 업로드 엑셀에서 찾을 열 이름 후보(왼쪽부터 우선)
USAGE_COLUMNS = {
    "employeeNo": ["사원번호", "직원번호", "Employee ID"],
    "name": ["직원", "성명", "이름", "직원명"],
    "org": ["조직들", "소속팀", "소속", "부서", "조직"],
    "group": ["휴가 그룹", "휴가그룹"],
    "type": ["휴가 유형", "휴가유형"],
    "start": ["시작 시간", "시작시간", "시작일자", "시작일", "시작 일시"],
    "deducted": ["차감 일수", "차감일수", "일수"],
}

ACCRUAL_COLUMNS = {
    "employeeNo": ["사원번호", "직원번호", "Employee ID"],
    "name": ["이름", "직원", "성명", "직원명"],
    "org": ["본조직", "조직들", "소속팀", "소속", "부서"],
    "group": ["휴가 그룹", "휴가그룹"],
    "state": ["상태"],
    "accrued": ["발생 일수", "발생일수"],
    "used": ["사용한 휴가 일수", "사용 일수", "사용일수"],
    "remain": ["남은 휴가 일수", "잔여 일수", "잔여일수", "잔여"],
    "grantStart": ["발생 시점", "발생시점"],
    "grantEnd": ["만료 시점", "만료시점"],
}

# 파일이 진짜 그 파일인지 확인할 때 쓰는 필수 열(하나라도 없으면 거절)
USAGE_REQUIRED = ["name", "group", "start", "deducted"]
ACCRUAL_REQUIRED = ["name", "group", "accrued", "used"]
