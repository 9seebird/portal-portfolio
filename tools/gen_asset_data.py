# -*- coding: utf-8 -*-
"""자산관리 앱에 넣을 가짜 데이터를 만든다.

만들기만 하고 **넣지는 않는다.** 결과는 JSON 한 덩어리로 나가고,
그걸 컨테이너 안의 `it-asset/backend/scripts/seed_demo.py` 가 받아서 넣는다.

왜 나눴나
────────
자산 앱의 표는 SQLAlchemy 모델이 정의한다. 그 모델을 읽으려면 앱과 같은
파이썬 환경이 필요한데, 그건 컨테이너 안에만 있다. 반대로 「누가 어느
팀이고 누가 무엇을 쓰는가」 같은 이야기는 다른 앱들과 맞아야 해서
tools/demo_company.py 옆에 있어야 한다.

그래서 이야기는 여기서 만들고, 넣는 일만 컨테이너가 한다.
사이를 오가는 것은 JSON 파일 하나뿐이라 서로의 사정을 몰라도 된다.

무엇을 신경 썼나
────────────────
숫자만 채우면 표는 차지만 **볼 것이 없다.** 화면이 무슨 일을 하는지
드러나려면 「어긋난 것」이 섞여 있어야 한다. 그래서 일부러 넣었다.

    · 퇴사자 2명이 자산과 라이선스를 **아직 반납하지 않은 상태**
    · 라이선스 2종이 **곧 만료** (12일 · 24일 남음)
    · 산 수량보다 **더 쓰고 있는** 라이선스 1종
    · 렌탈 계약 3건이 **3개월 안에 끝남**
    · 아무도 안 쓰는 빈 내선 · 빈 IP
    · 수리 중 · 폐기 자산

전부 실제로 겪는 일이고, 이 앱이 있는 이유이기도 하다.
"""

import random
from datetime import date, timedelta

import demo_company as C
import office_layout

# 만든 날을 기준으로 삼는다. 고정 날짜를 박아 두면 몇 달 뒤에 데모를
# 다시 띄웠을 때 「곧 만료」가 전부 「이미 만료」로 바뀌어, 알림 화면이
# 무슨 일을 하는지 안 보인다. 다시 만들면 늘 지금 기준이 된다.
TODAY = date.today()


def build() -> dict:
    r = random.Random(C.SEED + 1)
    people = C.people()

    out = {"employees": people}

    # ── 자산 ────────────────────────────────────────────────
    assets = []
    assign = []
    n = 0

    def new_asset(kind: str, **kw) -> dict:
        nonlocal n
        n += 1
        maker, models = r.choice(C.MAKERS[kind])
        a = {
            "asset_no": f"NC-{kind[:3]}-{n:04d}",
            "label_no": f"{n:04d}",
            "asset_type": kind,
            "manufacturer": maker,
            "model": r.choice(models),
            "serial_no": f"{maker[:2].upper()}{r.randint(10**9, 10**10 - 1)}",
            "status": "STORAGE",
            "purchase_type": "구매",
            "purchase_date": (TODAY - timedelta(days=r.randint(90, 1800))).isoformat(),
        }
        if kind in ("LAPTOP", "DESKTOP", "SERVER"):
            a["cpu"] = r.choice(C.CPUS)
            a["memory_gb"] = r.choice([8, 16, 16, 32, 32, 64])
            a["storage_gb"] = r.choice([256, 512, 512, 1024])
            a["os"] = r.choice(C.OSES)
        a.update(kw)
        assets.append(a)
        return a

    # 사람마다 PC 한 대 + 모니터 한두 대. 이게 자산의 대부분이다.
    for p in people:
        pc = new_asset("LAPTOP" if r.random() < 0.65 else "DESKTOP")
        # 40% 는 렌탈. 렌탈이 하나도 없으면 렌탈 화면이 텅 빈다.
        if r.random() < 0.4:
            pc["purchase_type"] = "렌탈"
            pc["rental_vendor"] = r.choice(C.RENTAL_VENDORS)
            pc["rental_end_date"] = (TODAY + timedelta(days=r.randint(-60, 700))).isoformat()

        if p["status"] == "ACTIVE":
            pc["status"] = "IN_USE"
            assign.append({"asset_no": pc["asset_no"], "emp_no": p["emp_no"],
                           "assigned_at": p["hire_date"]})
        else:
            # ★ 퇴사했는데 아직 반납이 안 된 상태로 둔다.
            #   자산관리에서 제일 자주 터지는 일이고, 이 앱이 그걸
            #   화면에 띄워 주는지 보여주는 자리다.
            pc["status"] = "IN_USE"
            assign.append({"asset_no": pc["asset_no"], "emp_no": p["emp_no"],
                           "assigned_at": p["hire_date"]})
            pc["notes"] = "퇴사자 미반납 — 확인 필요"

        for _ in range(r.choice([1, 1, 1, 2])):
            m = new_asset("MONITOR")
            if p["status"] == "ACTIVE":
                m["status"] = "IN_USE"
                assign.append({"asset_no": m["asset_no"], "emp_no": p["emp_no"],
                               "assigned_at": p["hire_date"]})

    # 공용 장비 · 예비 · 수리 · 폐기
    for _ in range(6):
        new_asset("SERVER", status="IN_USE", notes="전산실")
    for _ in range(9):
        new_asset("NETWORK", status="IN_USE", notes="층별 스위치")
    for _ in range(11):
        new_asset("OTHER", status="IN_USE", notes="공용 복합기")
    for _ in range(14):
        new_asset("LAPTOP", status="STORAGE", notes="예비 — 신규 입사 대기")
    for _ in range(5):
        new_asset("MONITOR", status="STORAGE")
    for _ in range(4):
        new_asset("LAPTOP", status="REPAIR", notes="배터리 부풀음 — 수리 접수")
    for _ in range(7):
        new_asset("DESKTOP", status="DISPOSED",
                  notes="내용연수 초과 — 2026년 상반기 폐기")

    out["assets"] = assets
    out["asset_assignments"] = assign

    # ── 렌탈 계약 ───────────────────────────────────────────
    # 자산의 렌탈 표시와 계약서를 따로 두는 이유 —
    # 계약은 여러 대를 한 장에 묶는 일이 많고, 월 비용은 계약에만 있다.
    contracts = []
    rented = [a for a in assets if a.get("purchase_type") == "렌탈"]
    for i, a in enumerate(rented, 1):
        end = date.fromisoformat(a["rental_end_date"])
        contracts.append({
            "asset_no": a["asset_no"],
            "vendor": a["rental_vendor"],
            "contract_no": f"RC-2026-{i:03d}",
            "start_date": (end - timedelta(days=36 * 30)).isoformat(),
            "end_date": end.isoformat(),
            "monthly_fee": r.choice([29000, 33000, 38000, 42000, 47000]),
            "status": "ACTIVE" if end >= TODAY else "ENDED",
        })
    # ★ 곧 끝나는 계약 3건은 **우연에 맡기지 않는다.**
    #   렌탈 화면의 핵심이 「두 달 안에 끝나는 것」인데, 날짜를 무작위로
    #   두면 어떤 날은 0건이 되어 그 화면이 텅 빈 채로 보인다.
    #   실제로 처음 만들었을 때 0건이 나왔다.
    for c, days in zip(contracts[:3], (12, 31, 48)):
        c["end_date"] = (TODAY + timedelta(days=days)).isoformat()
        c["status"] = "ACTIVE"
        for a in assets:
            if a["asset_no"] == c["asset_no"]:
                a["rental_end_date"] = c["end_date"]
    out["rental_contracts"] = contracts

    # ── 자리 배치 ───────────────────────────────────────────
    # 도면은 tools/office_layout.py 에 한 칸씩 적혀 있다. 여기서는
    # 그 도면에 사람만 앉힌다.
    #
    # 예전에는 이 자리에서 「팀 이름 줄 + 책상 여섯 개」를 층마다 찍어
    # 냈는데, 그건 배치도가 아니라 부서별 인원표를 세로로 세운 것이었다.
    # 통로도 기둥도 없고 회의실이 늘 맨 아래에 붙는 격자라서, 자리를
    # 옮기거나 빈 자리를 찾는 이 화면의 쓸모가 화면에 안 보였다.
    out["seats"] = office_layout.build_seats(people)

    # ── 내선 ────────────────────────────────────────────────
    exts = [{"number": p["ext"], "emp_no": p["emp_no"],
             "zone": p["floor"], "note": ""}
            for p in people if p["status"] == "ACTIVE"]
    # 빈 번호. 「남는 번호가 몇 개인가」가 이 화면의 첫 질문이다.
    for i in range(9):
        exts.append({"number": str(2900 + i), "emp_no": None,
                     "zone": "4F", "note": "미사용"})
    exts.append({"number": "2950", "emp_no": None, "zone": "1F",
                 "note": "안내데스크 공용"})
    out["extensions"] = exts

    # ── IP ──────────────────────────────────────────────────
    out["ip_ranges"] = [
        {"name": nm, "kind": k, "start_ip": s, "end_ip": e,
         "vlan": v, "gateway": g, "dns": d, "description": desc}
        for nm, k, s, e, v, g, d, desc in C.IP_RANGES
    ]
    ips = []
    host = 11
    for a in assets:
        if a["status"] != "IN_USE":
            continue
        if a["asset_type"] not in ("LAPTOP", "DESKTOP", "SERVER", "NETWORK"):
            continue
        if a["asset_type"] in ("SERVER", "NETWORK"):
            rng, base = "서버존", "10.20.40."
        else:
            rng, base = "사무실 유선", "10.20.30."
        if host > 200:
            break
        ips.append({
            "kind": "NETWORK", "range": rng, "asset_no": a["asset_no"],
            "ip_address": base + str(host),
            "hostname": a["asset_no"].lower().replace("nc-", "nc"),
            "mac_address": ":".join(f"{r.randint(0,255):02X}" for _ in range(6)),
            "status": "USED",
        })
        host += 1
    # 전화 대역은 내선에 붙는다 (자산이 아니라 사람 쪽)
    for i, e in enumerate(exts[:40]):
        if not e["emp_no"]:
            continue
        ips.append({"kind": "PHONE", "range": "IP 전화", "ext_number": e["number"],
                    "ip_address": f"10.20.50.{11 + i}",
                    "hostname": f"phone-{e['number']}",
                    "mac_address": ":".join(f"{r.randint(0,255):02X}" for _ in range(6)),
                    "status": "USED"})
    out["ip_assignments"] = ips

    # ── 소프트웨어 · 라이선스 ───────────────────────────────
    prods, pools, lic, installs = [], [], [], []
    actives = [p for p in people if p["status"] == "ACTIVE"]
    resigned = [p for p in people if p["status"] != "ACTIVE"]
    pcs = [a for a in assets
           if a["asset_type"] in ("LAPTOP", "DESKTOP") and a["status"] == "IN_USE"]

    for name, vendor, ltype, bought, days, desc in C.SOFTWARE:
        prods.append({"name": name, "vendor": vendor,
                      "license_type": ltype, "description": desc})
        pools.append({
            "software": name, "purchased_count": bought,
            "expire_date": (TODAY + timedelta(days=days)).isoformat() if days else None,
            "alert_days": 30,
        })
        # 누가 쓰고 있는지. 전 직원용은 전부, 나머지는 해당 팀 위주로.
        if bought >= 60:
            users = actives
        elif "Adobe" in name:
            users = [p for p in actives if p["department"] == "마케팅팀"]
        elif "AutoCAD" in name:
            users = [p for p in actives if p["department"] == "생산관리팀"][:3]
        elif "Tableau" in name:
            # ★ 산 것(4)보다 많이 준 상태로 둔다.
            #   「모자란다」가 화면에 뜨는지 보여주는 자리다.
            users = [p for p in actives if p["department"] in ("마케팅팀", "재무팀")][:6]
        else:
            users = r.sample(actives, min(len(actives), bought - 5))
        for p in users:
            lic.append({"software": name, "emp_no": p["emp_no"],
                        "assigned_at": p["hire_date"]})
        # ★ 퇴사자가 아직 들고 있는 라이선스. 돈이 계속 나가는 자리다.
        if name in ("Microsoft 365 Business", "카스퍼스키 엔드포인트"):
            for p in resigned:
                lic.append({"software": name, "emp_no": p["emp_no"],
                            "assigned_at": p["hire_date"],
                            "note": "퇴사자 미회수"})
        # 설치 기록 (PC 에 깔린 것)
        if name in ("카스퍼스키 엔드포인트", "한컴오피스", "알집", "SAP GUI"):
            for a in r.sample(pcs, min(len(pcs), bought)):
                installs.append({"software": name, "asset_no": a["asset_no"],
                                 "installed_at": a["purchase_date"]})

    out["software_products"] = prods
    out["license_pools"] = pools
    out["license_assignments"] = lic
    out["software_installations"] = installs
    return out


if __name__ == "__main__":
    import json
    import sys
    sys.path.insert(0, __file__.rsplit("/", 1)[0])
    d = build()
    for k, v in d.items():
        print(f"{k:24} {len(v):>5}")
    print(json.dumps(d, ensure_ascii=False)[:200])
