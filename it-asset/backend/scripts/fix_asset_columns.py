"""엑셀에서 한 칸씩 밀려 들어간 자산 정보를 정리한다.

증상
----
  모델      "16"            <- 사실은 메모리 용량
  CPU       "노트북"        <- 사실은 자산 유형
  운영체제  "10.20.40.86"    <- 사실은 IP 주소
  모델      "노트북-임대32" <- 유형+구분+메모리가 뭉쳐 들어간 것

엑셀 열 위치를 코드에 번호로 박아뒀는데(import_pc_list.py 의 value(row, 20) 같은 것),
실제 파일의 열 순서가 달라서 생긴 일이다. 이미 웹에서 손본 내용이 있으므로
엑셀을 다시 넣는 대신, 값의 생김새를 보고 잘못 들어간 것만 걷어낸다.

무엇을 하나
----------
  1. 운영체제 칸이 IP 주소면
       - 같은 IP 가 이미 IP 관리에 등록돼 있으면 -> 그냥 비운다
       - 등록돼 있지 않으면 -> 손대지 않고 알려만 준다 (--adopt-ip 로 등록 가능)
  2. CPU 칸이 '노트북/데스크탑/렌탈/구매' 같은 분류어면 비운다
  3. 모델 칸이 숫자만 있으면 (모델명이 "16" 일 수는 없다)
       - 메모리 칸이 비어 있으면 -> 메모리로 옮긴다
       - 메모리 칸에 이미 값이 있으면 -> 비운다
  4. 모델 칸이 '노트북-임대32' 처럼 유형+구분+숫자 뭉치면 비운다

기본은 '비우기'다. 유형·구분·IP 는 이미 각자 제 칸에 제대로 들어가 있어서,
옮기면 오히려 멀쩡한 값을 덮어쓴다. 예외는 메모리 하나다 —
메모리 칸이 비어 있는데 모델 칸에 숫자만 있으면 그게 유일한 메모리 정보이므로
버리지 않고 옮긴다.

사용법
------
  python scripts/fix_asset_columns.py              # 미리보기
  python scripts/fix_asset_columns.py --yes        # 적용
  python scripts/fix_asset_columns.py --yes --adopt-ip
        운영체제 칸에만 있고 IP 관리에는 없는 주소를 IP 관리에 등록하고 비운다
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

print("준비 중... (모델 로딩, 5~15초)", flush=True)

from app.db.database import SessionLocal
from app.models.asset import Asset
from app.models.ip_assignment import IPAssignment

print("준비 완료.", flush=True)

IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

# CPU 칸에 들어오면 안 되는 분류어
CATEGORY_WORDS = {
    "노트북", "데스크탑", "데스크톱", "모니터", "서버", "태블릿", "기타",
    "렌탈", "임대", "구매", "리스",
}

# 모델 칸의 "노트북-임대32", "데스크탑 구매 8" 같은 뭉치
LUMP = re.compile(r"^(노트북|데스크탑|데스크톱|모니터|서버|태블릿)"
                  r"[\s\-_]*(임대|렌탈|구매|리스)?[\s\-_]*\d*$")


def looks_like_ip(value: str | None) -> bool:
    if not value:
        return False
    text = value.strip()
    if not IPV4.match(text):
        return False
    return all(0 <= int(part) <= 255 for part in text.split("."))


def main() -> None:
    parser = argparse.ArgumentParser(description="밀려 들어간 자산 열 정리")
    parser.add_argument("--yes", action="store_true", help="실제로 고친다")
    parser.add_argument("--adopt-ip", action="store_true",
                        help="운영체제 칸에만 있는 IP 를 IP 관리에 등록한다")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        assets = db.query(Asset).all()
        known_ips = {
            (a.asset_id, a.ip_address)
            for a in db.query(IPAssignment.asset_id, IPAssignment.ip_address).all()
        }

        os_dupe, os_orphan, cpu_bad = [], [], []
        model_num, model_lump, model_to_memory = [], [], []

        for asset in assets:
            if looks_like_ip(asset.os):
                ip = asset.os.strip()
                if (asset.id, ip) in known_ips:
                    os_dupe.append((asset, ip))
                else:
                    os_orphan.append((asset, ip))

            if asset.cpu and asset.cpu.strip() in CATEGORY_WORDS:
                cpu_bad.append(asset)

            model = (asset.model or "").strip()
            if model.isdigit():
                # 메모리 칸이 비어 있으면 이 숫자가 유일한 메모리 정보다. 버리지 말고 옮긴다.
                if asset.memory_gb is None:
                    model_to_memory.append(asset)
                else:
                    model_num.append(asset)
            elif LUMP.match(model):
                model_lump.append(asset)

        def label(asset) -> str:
            # 자산번호가 비어 있는 자산이 있다. None 을 폭 지정 서식에 넣으면 터진다.
            return (asset.asset_no or asset.label_no or "(번호 없음)")[:16].ljust(16)

        def show(title, items, fmt):
            print(f"\n{title}: {len(items)}건")
            for item in items[:5]:
                print("   ", fmt(item))
            if len(items) > 5:
                print(f"    … 외 {len(items) - 5}건")

        print(f"\n자산 {len(assets)}대 검사")
        show("운영체제 칸이 IP (IP 관리에도 있음 → 비움)", os_dupe,
             lambda x: f"{label(x[0])} os={x[1]}")
        show("운영체제 칸이 IP (IP 관리에는 없음)", os_orphan,
             lambda x: f"{label(x[0])} os={x[1]}")
        show("CPU 칸이 분류어 (→ 비움)", cpu_bad,
             lambda a: f"{label(a)} cpu={a.cpu}")
        show("모델 칸이 숫자만, 메모리가 비어 있음 (→ 메모리로 옮김)", model_to_memory,
             lambda a: f"{label(a)} model={a.model} → memory={a.model}GB")
        show("모델 칸이 숫자만, 메모리는 이미 있음 (→ 비움)", model_num,
             lambda a: f"{label(a)} model={a.model}  memory={a.memory_gb}")
        show("모델 칸이 유형+구분 뭉치 (→ 비움)", model_lump,
             lambda a: f"{label(a)} model={a.model}")

        total = (len(os_dupe) + len(cpu_bad) + len(model_num)
                 + len(model_lump) + len(model_to_memory))
        if args.adopt_ip:
            total += len(os_orphan)

        if not args.yes:
            print(f"\n>>> 미리보기입니다. {total}건을 고치려면 --yes")
            if os_orphan and not args.adopt_ip:
                print("    운영체제 칸에만 있는 IP 도 정리하려면 --adopt-ip 를 함께")
            return

        for asset, _ip in os_dupe:
            asset.os = None
        for asset in cpu_bad:
            asset.cpu = None
        for asset in model_num:
            asset.model = None
        for asset in model_to_memory:
            asset.memory_gb = int(asset.model)
            asset.model = None
        for asset in model_lump:
            asset.model = None

        if args.adopt_ip:
            for asset, ip in os_orphan:
                db.add(IPAssignment(asset_id=asset.id, ip_address=ip, status="USED"))
                asset.os = None

        db.commit()
        print(f"\n>>> 완료: {total}건 정리")
        print("    화면에서 자산 목록을 열어 모델·CPU·운영체제 칸을 확인하세요.")
        print("    비워진 칸은 실제 값을 아시면 직접 채워 넣으면 됩니다.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
