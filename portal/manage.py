"""계정 관리 도구.

회원가입 화면이 없으므로 최초 관리자 계정은 이 스크립트로 만든다.
그 뒤부터는 웹 관리자 화면(/admin)에서 계정을 추가하면 된다.

사용:
    python manage.py add kim "김대리" --dept "인사총무팀" --password "Abcd123!"
    python manage.py add admin "관리자" --dept "인사총무팀" --admin --password "Abcd123!"
    python manage.py list
    python manage.py passwd kim
    python manage.py dept  kim "영업팀"
    python manage.py depts                 # 부서 목록
    python manage.py depts --add "품질관리팀"
    python manage.py admin kim on          # 관리자 권한 부여
    python manage.py admin kim off         # 관리자 권한 회수
    python manage.py off   kim             # 퇴사·휴직 처리
    python manage.py on    kim
    python manage.py purge-text            # 쌓인 질문·답변 원문 삭제

권한 모델:
    관리자(--admin) 는 관리자 화면과 전체 이력을 볼 수 있다.
    그 외 서비스별 접근 권한은 부서(dept) 기준으로 관리자 화면에서 지정한다.
    코드에 권한 이름을 넣지 않으므로 앱이 늘어도 이 파일은 바뀌지 않는다.
"""

import argparse
import getpass
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from app import depts, memory, services, titles, users  # noqa: E402

EPILOG = """
권한 안내
  --admin        관리자. /admin 화면에서 서비스·계정·이력을 관리할 수 있다.
  --dept         소속 부서. 서비스 접근 범위 판정의 기준이 된다.
                 등록된 부서 중에서만 지정할 수 있다. 목록은 depts 로 확인.
                 오타로 다른 부서가 만들어지면 그 사람은 아무것도 못 보게 된다.
"""


def _read(prompt: str) -> str:
    """비밀번호 입력.

    일부 윈도우 터미널에서 getpass 가 붙여넣기를 Ctrl+C 로 오인해
    KeyboardInterrupt 를 낸다. 그 경우 일반 입력으로 넘어간다.
    """
    try:
        return getpass.getpass(prompt)
    except (KeyboardInterrupt, EOFError, Exception):
        print("  (이 터미널에서는 입력이 화면에 보입니다)")
        return input(prompt)


def _resolve_password(given: str | None) -> str:
    """--password 로 받거나, 직접 입력받거나, 자동 생성한다."""
    if given:
        err = users.check_password(given)
        if err:
            print(err); sys.exit(1)
        return given

    p1 = _read("비밀번호 (그냥 Enter 치면 자동 생성): ").strip()
    if not p1:
        pw = users.suggest_password()
        print(f"\n  초기 비밀번호: {pw}")
        print("  본인에게 전달하세요. 첫 로그인 때 반드시 변경하게 됩니다.\n")
        return pw

    err = users.check_password(p1)
    if err:
        print(err); sys.exit(1)
    if p1 != _read("비밀번호 확인: ").strip():
        print("두 입력이 다릅니다."); sys.exit(1)
    return p1


def _check_dept(name: str) -> None:
    """등록되지 않은 부서를 막는다.

    부서명이 접근 판정의 기준이므로, 오타 하나가
    "권한을 줬는데 안 보인다"로 이어진다.
    """
    if not name:
        return
    if not depts.exists(name):
        print(f"등록되지 않은 부서입니다: {name}")
        cur = depts.all_depts()
        print("등록된 부서:", ", ".join(cur) if cur else "(없음)")
        print('먼저 등록하세요:  python manage.py depts --add "%s"' % name)
        sys.exit(1)


def cmd_add(a) -> None:
    if users.get(a.user_id):
        print(f"'{a.user_id}' 계정이 이미 있습니다.")
        sys.exit(1)
    _check_dept(a.dept)
    pw = _resolve_password(a.password)
    users.create(a.user_id, a.name, pw, dept=a.dept, is_admin=a.admin)
    print(f"생성 완료 — {a.user_id} ({a.name}) / 부서: {a.dept or '미지정'}"
          f" / {'관리자' if a.admin else '일반'}")
    if a.admin:
        print("이 계정으로 로그인한 뒤 /admin 에서 서비스와 계정을 관리하세요.")


def cmd_list(_) -> None:
    rows = users.all_users()
    if not rows:
        print("계정이 없습니다. python manage.py add 로 먼저 만드세요.")
        return
    print(f"{'아이디':<14}{'이름':<12}{'부서':<16}{'구분':<8}{'상태':<7}{'최근 로그인'}")
    print("─" * 88)
    for u in rows:
        print(
            f"{u['user_id']:<14}{u['name']:<12}{(u['dept'] or '-'):<16}"
            f"{'관리자' if u['is_admin'] else '일반':<8}"
            f"{'사용' if u['active'] else '중지':<7}"
            f"{u['last_login'] or '-'}"
        )


def cmd_passwd(a) -> None:
    if not users.get(a.user_id):
        print("없는 계정입니다."); sys.exit(1)
    users.set_password(a.user_id, _resolve_password(a.password), must_change=True)
    print("비밀번호를 변경했습니다. 본인이 첫 로그인 때 다시 정하게 됩니다.")


def cmd_dept(a) -> None:
    if not users.get(a.user_id):
        print("없는 계정입니다."); sys.exit(1)
    _check_dept(a.dept)
    users.update_profile(a.user_id, dept=a.dept)
    print(f"부서 변경 — {a.user_id}: {a.dept or '미지정'}")
    print("로그인 중인 사용자도 다음 요청부터 바로 반영됩니다.")


def cmd_admin(a) -> None:
    if not users.get(a.user_id):
        print("없는 계정입니다."); sys.exit(1)
    on = a.state == "on"
    # 마지막 관리자를 잃으면 관리자 화면에 아무도 못 들어간다
    if not on and users.admin_count(exclude=a.user_id) == 0:
        print("마지막 관리자입니다. 다른 계정에 관리자를 준 뒤 회수하세요.")
        sys.exit(1)
    users.update_profile(a.user_id, is_admin=on)
    print(f"{a.user_id} — {'관리자로 지정' if on else '관리자 권한 회수'}했습니다.")
    print("로그인 중인 사용자도 다음 요청부터 바로 반영됩니다.")


def cmd_depts(a) -> None:
    if a.add:
        if depts.create(a.add):
            print(f"부서 추가 — {a.add}")
        else:
            print(f"이미 있는 부서입니다: {a.add}")
        return

    cur = depts.all_depts()
    if not cur:
        print("등록된 부서가 없습니다. --add 로 추가하세요.")
        return
    print(f"{'부서':<18}{'소속':<8}{'이 부서를 쓰는 서비스'}")
    print("─" * 66)
    for d in cur:
        u = depts.usage(d)
        print(f"{d:<18}{str(len(u['users']))+'명':<8}"
              f"{', '.join(u['services']) or '-'}")


def cmd_purge_text(_) -> None:
    """이미 쌓인 질문·답변 원문을 지운다. 사용 기록 자체는 남는다.

    CHAT_LOG_TEXT=on 으로 쓰다가 끈 경우, 지난 기록은 그대로 남아 있다.
    """
    memory.init()
    n = memory.purge_chat_text()
    print(f"{n}건의 질문·답변 원문을 지웠습니다. (누가·언제·어떤 기능을 썼는지는 남습니다)")
    if memory.LOG_TEXT:
        print("주의 — CHAT_LOG_TEXT 가 아직 on 입니다. .env 에서 off 로 바꾸세요.")


def cmd_titles(a) -> None:
    """제목이 없는 지난 대화에 제목을 붙인다.

    제목 기능을 넣기 전에 만들어진 대화는 첫 질문이 그대로 제목으로 보인다.
    이 명령이 그 대화들을 하나씩 읽어 한 줄로 줄여 준다.

    대화 하나에 모델 호출 한 번이다. 수백 건이면 그만큼 든다.
    --limit 으로 조금씩 나눠 돌릴 수 있다.
    """
    memory.init()
    todo = memory.sessions_without_title(a.limit)
    if not todo:
        print("제목이 없는 대화가 없습니다.")
        return

    print(f"제목 없는 대화 {len(todo)}건. 하나씩 만듭니다. (--dry-run 으로 미리 볼 수 있습니다)")
    made = 0
    for i, s in enumerate(todo, 1):
        title = titles.make_now(s["question"], s["answer"])
        head = (s["question"] or "").strip().replace("\n", " ")[:24]
        if not title:
            print(f"  [{i}/{len(todo)}] 실패 — 그대로 둡니다 : {head}")
            continue
        if a.dry_run:
            print(f"  [{i}/{len(todo)}] {head}  →  {title}")
            continue
        memory.set_title(s["session_id"], s["user_id"], title)
        made += 1
        print(f"  [{i}/{len(todo)}] {head}  →  {title}")

    if a.dry_run:
        print("\n미리보기였습니다. 실제로 저장하려면 --dry-run 을 빼고 다시 실행하세요.")
    else:
        print(f"\n{made}건에 제목을 붙였습니다.")


def cmd_off(a) -> None:
    if users.admin_count(exclude=a.user_id) == 0 and (users.get(a.user_id) or {}).get("is_admin"):
        print("마지막 관리자입니다. 중지하면 관리자 화면에 들어갈 수 없습니다.")
        sys.exit(1)
    users.set_active(a.user_id, False)
    print(f"{a.user_id} 계정을 사용 중지했습니다. 다음 로그인부터 차단됩니다.")


def cmd_on(a) -> None:
    users.set_active(a.user_id, True)
    print(f"{a.user_id} 계정을 다시 사용 가능하게 했습니다.")


def main() -> None:
    users.init()
    depts.init()
    # 부서가 어느 서비스에 걸려 있는지 보여주려면 서비스 표도 있어야 한다
    services.init()

    ap = argparse.ArgumentParser(
        description="포털 계정 관리",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="계정 생성")
    p.add_argument("user_id"); p.add_argument("name")
    p.add_argument("--dept", default="", help="소속 부서 (예: 인사총무팀)")
    p.add_argument("--admin", action="store_true", help="관리자로 지정")
    p.add_argument("--password", help="지정하지 않으면 입력받거나 자동 생성")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("list", help="계정 목록"); p.set_defaults(fn=cmd_list)

    p = sub.add_parser("passwd", help="비밀번호 변경")
    p.add_argument("user_id")
    p.add_argument("--password", help="지정하지 않으면 입력받거나 자동 생성")
    p.set_defaults(fn=cmd_passwd)

    p = sub.add_parser("dept", help="부서 변경")
    p.add_argument("user_id"); p.add_argument("dept")
    p.set_defaults(fn=cmd_dept)

    p = sub.add_parser("depts", help="부서 목록 / 추가")
    p.add_argument("--add", help="부서 추가")
    p.set_defaults(fn=cmd_depts)

    p = sub.add_parser("admin", help="관리자 권한 부여/회수")
    p.add_argument("user_id"); p.add_argument("state", choices=["on", "off"])
    p.set_defaults(fn=cmd_admin)

    p = sub.add_parser("off", help="계정 사용 중지")
    p.add_argument("user_id"); p.set_defaults(fn=cmd_off)

    p = sub.add_parser("on", help="계정 사용 재개")
    p.add_argument("user_id"); p.set_defaults(fn=cmd_on)

    p = sub.add_parser("purge-text", help="쌓인 질문·답변 원문 삭제")
    p.set_defaults(fn=cmd_purge_text)

    p = sub.add_parser("titles", help="제목 없는 지난 대화에 제목 붙이기 (주제 + 대상 형식)")
    p.add_argument("--limit", type=int, default=200, help="한 번에 처리할 건수 (기본 200)")
    p.add_argument("--dry-run", action="store_true", help="저장하지 않고 결과만 보기")
    p.set_defaults(fn=cmd_titles)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
