"""역할(roles) → 부서·관리자 전환. 1회용.

권한 모델을 역할 이름에서 부서 기준으로 바꾸면서, 기존 계정의
roles 값이 쓰이지 않게 되었다. 컬럼은 자동으로 추가되지만
값은 옮겨지지 않으므로 **관리자가 관리자 자격을 잃는다.**
이 스크립트가 그 부분을 메운다.

    python migrate_roles.py            # 무엇이 바뀔지 보기만 함
    python migrate_roles.py --apply    # 실제 반영

전환 규칙:
    roles 에 it_admin 이 있으면  -> 관리자
    부서는 비어 있으므로 --dept 로 일괄 지정하거나
    반영 후 관리자 화면에서 사람별로 채운다.

부서를 채우지 않으면 부서 지정형 서비스가 아무에게도 보이지 않는다.
반영 뒤에는 반드시 부서를 채울 것.
"""

import argparse
import os
import sqlite3
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DB = os.environ.get("USER_DB", "./data/users.db")

# 관리자로 볼 역할 이름. 예전에 쓰던 이름을 넣어 두었다.
ADMIN_ROLES = {"it_admin", "admin"}


def main() -> None:
    ap = argparse.ArgumentParser(description="roles → dept/is_admin 전환")
    ap.add_argument("--apply", action="store_true", help="실제로 반영")
    ap.add_argument("--dept", default="", help="부서가 비어 있는 계정에 일괄 지정할 부서")
    a = ap.parse_args()

    if not os.path.exists(DB):
        print(f"DB 를 찾을 수 없습니다: {DB}")
        sys.exit(1)

    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    cols = {r[1] for r in c.execute("PRAGMA table_info(users)")}
    if "roles" not in cols:
        print("roles 컬럼이 없습니다. 이미 전환되었거나 새로 만든 DB 입니다.")
        return
    if "is_admin" not in cols:
        print("is_admin 컬럼이 없습니다. 서버를 한 번 실행해 컬럼을 만든 뒤 다시 실행하세요.")
        sys.exit(1)

    rows = list(c.execute("SELECT user_id,name,roles,dept,is_admin FROM users"))
    if not rows:
        print("계정이 없습니다.")
        return

    print(f"{'아이디':<12}{'이름':<10}{'기존 roles':<28}{'→ 구분':<8}{'→ 부서'}")
    print("─" * 74)

    plan = []
    for r in rows:
        roles = {x.strip() for x in (r["roles"] or "").split(",") if x.strip()}
        is_admin = 1 if roles & ADMIN_ROLES else int(r["is_admin"] or 0)
        dept = r["dept"] or a.dept
        plan.append((r["user_id"], dept, is_admin))
        print(f"{r['user_id']:<12}{r['name']:<10}{(r['roles'] or '-'):<28}"
              f"{'관리자' if is_admin else '일반':<8}{dept or '(미지정)'}")

    admins = sum(1 for _, _, ad in plan if ad)
    print("─" * 74)
    print(f"관리자 {admins}명")
    if admins == 0:
        print("\n주의 — 관리자가 한 명도 없습니다. 이대로 반영하면 /admin 에 들어갈 수 없습니다.")
        print("      manage.py admin <아이디> on 으로 따로 지정하세요.")

    if not a.apply:
        print("\n(확인만 했습니다. 실제로 반영하려면 --apply 를 붙이세요.)")
        print("  예) python migrate_roles.py --apply --dept \"인사총무팀\"")
        return

    with c:
        for uid, dept, is_admin in plan:
            c.execute("UPDATE users SET dept=?, is_admin=? WHERE user_id=?",
                      (dept, is_admin, uid))
    print("\n반영했습니다.")
    if not a.dept and any(not d for _, d, _ in plan):
        print("부서가 비어 있는 계정이 있습니다. 관리자 화면의 사용자 명부에서 채우세요.")
        print("부서가 비면 부서 지정형 서비스가 그 사람에게 보이지 않습니다.")
    print("이미 로그인 중인 사용자는 다시 로그인해야 반영됩니다.")


if __name__ == "__main__":
    main()
