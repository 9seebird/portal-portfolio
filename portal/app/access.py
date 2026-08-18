"""접근 범위 판정.

이 파일 하나가 "누가 무엇을 볼 수 있는가"의 유일한 기준이다.
좌측 앱 목록, 앱 런처, 챗 도구 노출, 도구 실행 — 전부 이 함수를 거친다.
판정 로직이 여러 군데로 흩어지면 "화면엔 보이는데 챗에선 안 된다" 같은
불일치가 생기고, 그게 가장 위험하다.

판정 순서:
    1. IP 제한에 걸림            -> 불가 (관리자도 예외 없음)
    2. 사용 중지된 서비스        -> 불가 (관리자도 예외 없음)
    3. 포털 관리자               -> 가능
    4. 제외 명단에 있음          -> 불가 (부서가 허용이어도 우선)
    5. access = all              -> 가능
    6. 개별 허용 명단에 있음     -> 가능
    7. 소속 부서가 허용 목록에   -> 가능
    8. 그 외                     -> 불가

IP 제한은 목록이 비어 있으면 검사하지 않는다.
"""

from .registry import User


def can_use(user: User, svc: dict, ip: str | None = None,
            *, as_member: bool = False) -> bool:
    """이 사람이 이 서비스를 쓸 수 있는가.

    as_member=True 면 **관리자 특권을 빼고** 본다. 화면에서
    「내 범위만 보기」를 켰을 때 쓴다. 관리자는 모든 앱이 보이는데,
    앱이 늘수록 정작 자기가 쓰는 것을 찾기 어려워진다.
    이건 권한을 바꾸는 것이 아니라 **눈에 보이는 것만** 줄이는 것이다.
    """

    # IP 제한은 누구에게나 적용된다. 관리자여도 허용되지 않은 곳에서는 못 들어간다.
    # 이건 "누구인가"가 아니라 "어디서 접속하는가"의 문제다.
    ips = svc.get("allowed_ips") or []
    if ips and ip and ip not in ips:
        return False

    # 사용 중지도 누구에게나 적용된다. 관리자만 예외로 두면
    # "중지했는데 왜 되지?" 가 생기고, 중지라는 말의 뜻이 흔들린다.
    # 새 앱을 확인하려면 켠 다음에 접근 범위를 비워 두면 된다.
    # 그러면 관리자만 들어갈 수 있다 (아래 규칙 때문에).
    if not svc.get("enabled", True):
        return False

    # 포털 관리자는 접근 범위와 무관하게 통과한다.
    # 방금 배포한 앱을 바로 열어 확인해야 하고, 담당자가 퇴사했을 때
    # 아무도 손댈 수 없게 되는 상황을 막아야 한다.
    # 대신 관리자는 모든 앱의 업무 데이터를 볼 수 있게 되므로,
    # 관리자 계정은 꼭 필요한 사람에게만 준다.
    if user.is_admin and not as_member:
        return True

    if user.user_id in (svc.get("excluded_users") or []):
        return False

    if svc.get("access") == "all":
        return True

    if user.user_id in (svc.get("allowed_users") or []):
        return True

    if user.dept and user.dept in (svc.get("allowed_depts") or []):
        return True

    return False


def can_manage(user: User, svc: dict) -> bool:
    """이 서비스의 담당자인가.

    파일 삭제처럼 되돌릴 수 없는 동작에 쓴다.
    "쓸 수 있다(can_use)"와 "관리할 수 있다(can_manage)"는 다른 문제다.
    부서 전체가 리포트를 볼 수 있어도, 남이 올린 파일을 지우는 건
    한두 사람만 할 수 있어야 한다.

    포털 관리자는 목록에 없어도 담당자로 본다. 담당자가 퇴사했을 때
    아무도 손댈 수 없게 되는 상황을 막는다.
    """
    if user.is_admin:
        return True
    return user.user_id in (svc.get("managers") or [])


def visible(user: User, services: list[dict], ip: str | None = None) -> list[dict]:
    """이 사용자에게 보여줄 서비스만 추린다."""
    return [s for s in services if can_use(user, s, ip)]


def describe(svc: dict) -> str:
    """관리자 화면에 표시할 접근 범위 요약."""
    if svc.get("access") == "all":
        return "전 직원"

    parts = []
    d = svc.get("allowed_depts") or []
    u = svc.get("allowed_users") or []
    x = svc.get("excluded_users") or []
    if d:
        parts.append(f"부서 {len(d)}개 ({', '.join(d[:2])}{' 외' if len(d) > 2 else ''})")
    if u:
        parts.append(f"개인 {len(u)}명")
    if x:
        parts.append(f"제외 {len(x)}명")
    if svc.get("allowed_ips"):
        parts.append(f"IP {len(svc['allowed_ips'])}개")
    return " · ".join(parts) if parts else "지정 없음 (아무도 볼 수 없음)"


def describe_managers(svc: dict) -> str:
    n = len(svc.get("managers") or [])
    return f"담당자 {n}명" if n else "담당자 없음 (관리자만)"
