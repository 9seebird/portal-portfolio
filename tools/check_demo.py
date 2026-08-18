# -*- coding: utf-8 -*-
"""체험판 안전장치가 실제로 막고 있는지 확인한다.

    python3 tools/check_demo.py                 (http://localhost)
    python3 tools/check_demo.py https://내주소

배포한 뒤 **한 번은 꼭 돌린다.** 이 검사는 설정 파일을 읽지 않는다.
바깥에서 진짜로 요청을 보내 본다. 그래야 「고쳤다고 생각했는데 안
고쳐진 것」이 잡힌다.

────────────────────────────────────────────────────────────
왜 이 검사가 따로 필요한가

막는 코드가 두 군데에 있다. 포털 미들웨어(portal/app/demo.py)와
nginx(proxy/conf.d/00-demo-guard.conf). 둘 중 **하나만** 켜져 있어도
겉으로는 멀쩡히 막힌 것처럼 보인다.

그래서 코드를 읽는 대신 결과만 본다. 막혀야 할 것이 막히고, 열려야 할
것이 열리는가. 어느 쪽이 막았는지는 여기서 따지지 않는다.

한 번 크게 틀렸던 자리 —
nginx 가 내보내는 403 본문이 **JSON 으로 안 읽히는 상태**였다.
상태 코드는 403 으로 멀쩡해서 이 검사에 「막힘」으로 찍혔지만,
브라우저에서는 안내문 대신 "알 수 없는 오류" 만 떴다.
그래서 지금은 본문이 JSON 으로 읽히는지도 함께 본다.
"""
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost").rstrip("/")
ok = fail = 0

# ★ 로그인부터 하고 시작한다.
#   안 하면 앱 주소들이 전부 401/403 으로 돌아오는데, 그게 「막혔다」와
#   구분이 안 된다. 안전장치가 다 꺼져 있어도 전부 통과로 찍힌다.
#   실제로 위험한 검사는 **늘 통과하는 검사**다.
JAR = http.cookiejar.CookieJar()
WEB = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JAR))


def hit(method: str, path: str):
    """(상태코드, 본문) — 못 붙으면 (0, 사유)"""
    req = urllib.request.Request(BASE + path, method=method,
                                 data=b"{}" if method != "GET" else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with WEB.open(req, timeout=20) as r:
            return r.status, r.read(4000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(4000).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def login(user_id: str, password: str) -> bool:
    req = urllib.request.Request(
        BASE + "/api/login", method="POST",
        data=json.dumps({"user_id": user_id, "password": password}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with WEB.open(req, timeout=20) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def case(method: str, path: str, want_block: bool, why: str = ""):
    global ok, fail
    code, body = hit(method, path)
    blocked = code in (403, 429)
    good = (blocked == want_block)

    note = ""
    if blocked:
        # 막는 것까지는 맞는데 안내문이 안 읽히면 화면에는 아무 말도 안 나온다.
        try:
            d = json.loads(body)
            note = "· " + str(d.get("detail", ""))[:34].replace("\n", " ")
        except Exception:  # noqa: BLE001
            good = False
            note = "· ✗ 본문이 JSON 이 아니다 (화면에 안내가 안 뜬다)"
    elif code == 0:
        good = False
        note = "· 붙지 못함: " + body[:40]

    print(("  통과  " if good else "  실패  ")
          + f"{method:<6} {path:<42} {code:<4} " + note + (f"  {why}" if why else ""))
    ok += good
    fail += (not good)


print(f"■ 대상 {BASE}")
d = None
try:
    _, b = hit("GET", "/api/demo")
    d = json.loads(b)
except Exception:  # noqa: BLE001
    pass
if not (d or {}).get("demo"):
    print("  ✗ 체험판이 아닙니다. portal/.env 의 DEMO_MODE 를 확인하세요.")
    sys.exit(1)
print(f"  체험 계정 {d['user_id']} · 챗 IP당 하루 {d['chat_per_ip_day']}회 "
      f"· 이번 달 남은 토큰 {d['tokens_left']:,}")
if not login(d["user_id"], d["password"]):
    print("  ✗ 체험 계정으로 로그인하지 못했습니다. 이대로는 검사가 무의미합니다.")
    sys.exit(1)
print("  로그인 OK — 이제부터는 「권한이 없어서」가 아니라 「막아서」 막힌 것이다")

print("\n■ 막혀야 한다 — 다음 사람에게 남는 것")
case("POST",   "/api/me/password",            True, "← 이게 뚫리면 데모가 끝난다")
case("POST",   "/api/admin/users",            True)
case("PATCH",  "/api/admin/users/demo",       True)
case("DELETE", "/api/admin/users/demo",       True)
case("POST",   "/api/admin/departments",      True)
case("DELETE", "/api/admin/services/x",       True)
case("POST",   "/api/services/register",      True, "← 바깥에서는 앱 등록도 막는다")
case("POST",   "/it-asset/api/assets",        True)
case("PUT",    "/it-asset/api/employees/1",   True)
case("DELETE", "/it-asset/api/assets/1",      True)
# 자리 배치는 **옮기기만** 열었다. 아래 셋은 그대로 막혀야 한다.
# 칸을 지우거나 새로 만든 것은 화면의 되돌리기로도 안 돌아온다.
case("POST",   "/it-asset/api/seats",         True, "← 칸 만들기는 막는다")
case("DELETE", "/it-asset/api/seats/1",       True, "← 칸 삭제는 막는다")
case("PUT",    "/it-asset/api/seats/1/employee", True, "← 사람 앉히기도 막는다")
case("POST",   "/manual-import/api/apply",    True)
case("DELETE", "/manual-import/api/manuals/1", True)
case("POST",   "/leave-anomaly/api/holidays", True)
case("POST",   "/leave-anomaly/api/datasets/leave", True)
case("POST",   "/ai-report/api/upload",       True)
case("DELETE", "/ai-report/api/files/x.xlsx", True)

print("\n■ 열려야 한다 — 계산하고 버리는 것")
# 여기서는 401/422/400 이 나와도 좋다. 「막히지 않았다」만 보면 된다.
case("POST", "/api/login",                    False)
case("POST", "/api/chat",                     False)
case("POST", "/api/upload",                   False)
case("POST", "/biz-plan/api/run",             False)
case("POST", "/biz-plan/api/recompute",       False)
case("POST", "/biz-plan/api/export",          False)
case("POST", "/intake/api/check/회의실예약",   False)
case("POST", "/manual-import/api/preview",    False)
case("GET",  "/it-asset/api/assets",          False, "← 읽기는 전부 열려 있다")
# 배치도를 끌어 옮기는 것. 이 앱에서 제일 보여줄 만한 화면이라 열어 두었다.
# 되돌리기 버튼이 있고, 틀어져도 배치 자료를 다시 넣으면 원래대로 돌아온다.
case("PATCH", "/it-asset/api/seats/1",        False, "← 자리 옮기기는 열어 두었다")
case("GET",  "/",                             False)

print(f"\n{ok}개 통과 · {fail}개 실패")
sys.exit(1 if fail else 0)
