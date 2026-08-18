"""휴가 이상감지 분석 엔진.

Team Planner(oz.js)의 판정 로직을 파이썬으로 그대로 옮긴 것이다.
① 이상 패턴(고립 연차 반복) ② 저사용(쌓아두기) ③ 급증(몰아쓰기) 세 가지를 계산한다.
"""

from __future__ import annotations

from datetime import date, timedelta

from .config import ANOMALY_CONFIG


# --------------------------------------------------------------------------
# 날짜 도우미
# --------------------------------------------------------------------------
def parse_key(key: str) -> date:
    """"YYYY-MM-DD" 문자열을 날짜로 바꾼다."""
    y, m, d = (int(x) for x in key.split("-"))
    return date(y, m, d)


def to_key(value: date) -> str:
    """날짜를 "YYYY-MM-DD" 문자열로 바꾼다."""
    return value.isoformat()


def weekday_num(key: str) -> int:
    """월=1 … 금=5, 토=6, 일=0 (자바스크립트 getDay()와 같은 규칙)."""
    return (parse_key(key).weekday() + 1) % 7


def days_between(from_key: str, to_key_: str) -> int:
    """두 날짜 사이의 일수(뒤 - 앞)."""
    return (parse_key(to_key_) - parse_key(from_key)).days


def prev_workday(key: str) -> str:
    """주말을 건너뛴 직전 근무일."""
    d = parse_key(key) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return to_key(d)


def next_workday(key: str) -> str:
    """주말을 건너뛴 다음 근무일."""
    d = parse_key(key) + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return to_key(d)


def fmt_days(value: float) -> float:
    """0.125 같은 소수 일수를 오차 없이 다듬는다."""
    return round(float(value or 0), 3)


# --------------------------------------------------------------------------
# 하루 단위 분류
# --------------------------------------------------------------------------
def classify_day(total: float, hour, date_key: str) -> dict:
    """하루치 연차 합계를 유형(연차/반차/반반차…)으로 분류하고 요일 가중치를 매긴다."""
    is_pm = bool(hour is not None and hour >= 12)
    wd = weekday_num(date_key)
    t = round(total * 1000) / 1000
    if t >= 1 - 0.001:
        cat, label = "fullAnnual", "연차(전일)"
    elif abs(t - 0.75) < 0.001:
        cat = "halfPM" if is_pm else "halfAM"
        label = ("반차·오후" if is_pm else "반차·오전") + " (합산 0.75)"
    elif abs(t - 0.5) < 0.001:
        cat = "halfPM" if is_pm else "halfAM"
        label = "반차·오후" if is_pm else "반차·오전"
    elif abs(t - 0.25) < 0.001:
        cat = "quarterPM" if is_pm else "quarterAM"
        label = "반반차·오후" if is_pm else "반반차·오전"
    elif abs(t - 0.125) < 0.001:
        cat = "eighthPM" if is_pm else "eighthAM"
        label = "반반반차·오후" if is_pm else "반반반차·오전"
    else:
        cat = "halfPM" if is_pm else "halfAM"
        label = f"혼합 {fmt_days(t)} (반차 적용)"
    weights = ANOMALY_CONFIG["weights"].get(cat, {})
    return {"label": label, "weight": float(weights.get(wd, 0))}


def build_person_days(rows: list[dict]) -> dict:
    """사람×날짜로 묶는다. 같은 날 여러 건은 차감일수를 합산한다(반차+반차=연차)."""
    best: dict[str, dict] = {}
    for row in rows:
        if not row.get("name") or not row.get("date") or not (row.get("deducted", 0) > 0):
            continue
        sig = f"{row['name']}|{row['date']}|{row.get('hour')}|{row['deducted']}"
        prev = best.get(sig)
        # 같은 내용이 다른(임시) 사원번호로 중복 기록된 경우 더 긴(진짜) 번호를 남긴다.
        if not prev or len(str(row.get("employeeNo") or "")) > len(str(prev.get("employeeNo") or "")):
            best[sig] = row

    by_person_day: dict[str, dict] = {}
    for row in best.values():
        person = row.get("employeeNo") or row["name"]
        key = f"{person}|{row['date']}"
        day = by_person_day.get(key)
        if day is None:
            day = {
                "person": person, "name": row["name"], "org": row.get("org", ""),
                "date": row["date"], "total": 0.0, "minHour": None, "maxHour": None,
            }
            by_person_day[key] = day
        day["total"] += row["deducted"]
        hour = row.get("hour")
        if hour is not None:
            day["minHour"] = hour if day["minHour"] is None else min(day["minHour"], hour)
            day["maxHour"] = hour if day["maxHour"] is None else max(day["maxHour"], hour)

    by_person: dict[str, dict] = {}
    for day in by_person_day.values():
        info = classify_day(day["total"], day["minHour"], day["date"])
        is_full = day["total"] >= 1 - 0.001
        # 부재가 하루의 어느 쪽 끝에 닿는지(연속 판정용)
        start_am = is_full or (day["minHour"] < 12 if day["minHour"] is not None else True)
        end_pm = is_full or (day["maxHour"] >= 12 if day["maxHour"] is not None else True)
        event = {
            "date": day["date"],
            "deducted": round(day["total"] * 1000) / 1000,
            "weight": info["weight"],
            "label": info["label"],
            "startAM": start_am,
            "endPM": end_pm,
        }
        entry = by_person.setdefault(day["person"], {"name": day["name"], "org": day["org"], "days": []})
        entry["days"].append(event)

    for entry in by_person.values():
        entry["days"].sort(key=lambda e: e["date"])
    return by_person


# --------------------------------------------------------------------------
# ① 이상 패턴
# --------------------------------------------------------------------------
def is_isolated_event(row: dict, person_day_map: dict, day_headcount: dict, holiday_keys: set) -> bool:
    """이 연차가 '고립'인지 판정한다.

    고립 = 공휴일·회사휴일이 앞뒤로 붙지 않고, 본인의 다른 연차와 부재가 실제로 이어지지 않으며,
    전사 집단연차일(50%↑)이 아닌 평일 연차.
    """
    key = row["date"]
    wd = weekday_num(key)
    if wd in (0, 6):  # 주말은 애초에 대상 아님
        return False
    prev = prev_workday(key)
    nxt = next_workday(key)
    if prev in holiday_keys or nxt in holiday_keys:
        return False
    prev_day = person_day_map.get(prev)
    nxt_day = person_day_map.get(nxt)
    if prev_day and prev_day["endPM"] and row["startAM"]:
        return False  # 앞날 오후~이 날 오전으로 부재가 이어짐
    if nxt_day and nxt_day["startAM"] and row["endPM"]:
        return False  # 이 날 오후~뒷날 오전으로 부재가 이어짐
    total = day_headcount["total"] or 1
    if total > 0 and day_headcount["byDate"].get(key, 0) / total >= ANOMALY_CONFIG["massLeaveRatio"]:
        return False
    return True


def analyze_pattern(usage_rows: list[dict], holiday_keys: set) -> list[dict]:
    """고립 연차가 21일 창 안에서 반복되는 사람을 위험/검토/관찰로 분류해 돌려준다."""
    by_person = build_person_days(usage_rows)
    total = len(by_person)
    by_date: dict[str, int] = {}
    for person in by_person.values():
        for day in person["days"]:
            by_date[day["date"]] = by_date.get(day["date"], 0) + 1
    day_headcount = {"total": total, "byDate": by_date}
    tiers = ANOMALY_CONFIG["tiers"]
    danger, review, observe = tiers["danger"], tiers["review"], tiers["observe"]
    window_days = ANOMALY_CONFIG["windowDays"]

    episodes: list[dict] = []
    for person in by_person.values():
        person_day_map = {d["date"]: d for d in person["days"]}
        isolated = [d for d in person["days"] if is_isolated_event(d, person_day_map, day_headcount, holiday_keys)]
        if len(isolated) < 2:
            continue

        windows = []
        for row in isolated:
            start_bound = to_key(parse_key(row["date"]) - timedelta(days=window_days - 1))
            events = [r for r in isolated if start_bound <= r["date"] <= row["date"]]
            score = sum(r["weight"] for r in events)
            tier = None
            if score >= danger["minScore"] and len(events) >= danger["minCount"]:
                tier = danger["label"]
            elif score >= review["minScore"] or len(events) >= review["minCount"]:
                tier = review["label"]
            elif score >= observe["minScore"]:
                tier = observe["label"]
            windows.append({"date": row["date"], "score": score, "count": len(events), "events": events, "tier": tier})

        runs, current = [], []
        for w in windows:
            if w["tier"]:
                current.append(w)
            elif current:
                runs.append(current)
                current = []
        if current:
            runs.append(current)

        person_episodes = []
        for run in runs:
            best = max(run, key=lambda w: w["score"])
            person_episodes.append({
                "name": person["name"],
                "org": person["org"],
                "detectedDate": best["date"],
                "score": round(best["score"], 2),
                "count": best["count"],
                "tier": best["tier"],
                "events": sorted(best["events"], key=lambda e: e["date"], reverse=True),
            })
        person_episodes.sort(key=lambda e: e["detectedDate"])
        for index, episode in enumerate(person_episodes):
            episode["round"] = index + 1
            episode["rounds"] = len(person_episodes)
        episodes.extend(person_episodes)

    episodes.sort(key=lambda e: e["detectedDate"], reverse=True)
    return episodes


# --------------------------------------------------------------------------
# ② 저사용
# --------------------------------------------------------------------------
def analyze_low_usage(accrual_rows: list[dict], ref_key: str) -> dict:
    """연중 경과율보다 사용률이 크게 낮은(연차를 쌓아두는) 사람을 찾는다."""
    cfg = ANOMALY_CONFIG["lowUsage"]
    ref = parse_key(ref_key)
    day_of_year = (ref - date(ref.year, 1, 1)).days + 1
    elapsed_pct = (day_of_year / cfg["yearDays"]) * 100

    seen: set[str] = set()
    by_person: dict[str, dict] = {}
    for row in accrual_rows:
        state = row.get("state") or ""
        if state and state != "발생됨":
            continue
        if row.get("grantStart") and ref_key < row["grantStart"]:
            continue
        if row.get("grantEnd") and ref_key > row["grantEnd"]:
            continue
        sig = f"{row.get('name')}|{row.get('grantStart')}|{row.get('grantEnd')}|{row.get('accrued')}|{row.get('used')}"
        if sig in seen:
            continue
        seen.add(sig)
        key = row.get("employeeNo") or row.get("name")
        acc = by_person.setdefault(key, {"name": row.get("name"), "org": row.get("org", ""), "accrued": 0.0, "used": 0.0, "remain": 0.0})
        acc["accrued"] += row.get("accrued", 0)
        acc["used"] += row.get("used", 0)
        acc["remain"] += row.get("remain", 0)

    rows = []
    for person in by_person.values():
        if person["accrued"] < cfg["minAccrued"]:
            continue
        use_pct = (person["used"] / person["accrued"]) * 100 if person["accrued"] else 0
        gap = elapsed_pct - use_pct
        if gap >= cfg["gapPoint"]:
            rows.append({
                "name": person["name"], "org": person["org"],
                "accrued": fmt_days(person["accrued"]), "used": fmt_days(person["used"]),
                "remain": fmt_days(person["remain"]),
                "usePct": round(use_pct, 1), "gap": round(gap, 1),
            })
    rows.sort(key=lambda r: r["gap"], reverse=True)
    return {"rows": rows, "elapsedPct": round(elapsed_pct, 1), "dayOfYear": day_of_year}


# --------------------------------------------------------------------------
# ③ 급증
# --------------------------------------------------------------------------
def analyze_spike(usage_rows: list[dict], ref_key: str) -> list[dict]:
    """최근 60일 사용량이 직전 기간 기대치의 2.5배 이상인(몰아쓰는) 사람을 찾는다."""
    cfg = ANOMALY_CONFIG["spike"]
    by_person = build_person_days(usage_rows)
    out = []
    for person in by_person.values():
        days = [d for d in person["days"] if d["date"] <= ref_key]
        recent = [d for d in days if days_between(d["date"], ref_key) < cfg["windowDays"]]
        prior = [d for d in days if days_between(d["date"], ref_key) >= cfg["windowDays"]]
        recent_days = sum(d["deducted"] for d in recent)
        expected = 0.0
        if prior:
            span = max(1, days_between(prior[0]["date"], ref_key) - cfg["windowDays"])
            expected = (sum(d["deducted"] for d in prior) / span) * cfg["windowDays"]
        if recent_days >= cfg["minRecentDays"] and recent_days >= max(2, expected * cfg["ratio"]):
            out.append({
                "name": person["name"], "org": person["org"],
                "recentDays": fmt_days(recent_days),
                "expected": round(expected, 2),
                "ratio": round(recent_days / expected, 1) if expected > 0 else None,
                "recentDates": [d["date"] for d in recent],
            })
    out.sort(key=lambda r: r["recentDays"], reverse=True)
    return out


# --------------------------------------------------------------------------
# 통합
# --------------------------------------------------------------------------
def analyze_all(usage_rows: list[dict], accrual_rows: list[dict], ref_key: str, holiday_keys: set) -> dict:
    """세 가지 감지를 한 번에 돌리고, 오전/오후 판정이 안 된 건수도 함께 알려준다."""
    unknown_ampm = sum(
        1 for row in usage_rows
        if row.get("deducted", 0) < 1 and row.get("hour") is None
        and "오전" not in (row.get("type") or "") and "오후" not in (row.get("type") or "")
    )
    return {
        "refDate": ref_key,
        "episodes": analyze_pattern(usage_rows, holiday_keys),
        "lowUsage": analyze_low_usage(accrual_rows, ref_key),
        "spikes": analyze_spike(usage_rows, ref_key),
        "unknownAmPm": unknown_ampm,
    }
