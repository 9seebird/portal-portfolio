"""manuals.js 를 읽고 쓴다.

이 파일은 자바스크립트지만 `window.MANUAL_DATA =` 뒤는 그냥 JSON 이다.
매뉴얼 화면의 편집 모드가 만들어 내는 모양을 **그대로** 유지한다.
모양이 달라지면 편집 모드로 저장한 파일과 여기서 만든 파일이 갈라지고,
나중에 어느 쪽이 맞는지 알 수 없게 된다.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))

# it-guide/web/manuals 가 이 경로로 붙는다 (docker-compose 볼륨)
ROOT = Path(os.getenv("MANUALS_DIR", "/manuals"))
DATA = ROOT / "data" / "manuals.js"
IMAGES = ROOT / "images"
BACKUP = ROOT / "data" / "backup"
SOURCES = ROOT / "sources"          # 올린 PPT 원본을 그대로 둔다

HEADER = """// 온빛 IT 매뉴얼 포털 - 내용 파일
// 포털의 "편집 모드"에서 수정 후 저장하면 이 파일이 새로 만들어집니다.
// 직접 편집해도 됩니다. (이미지 경로는 images/ 폴더 기준)
window.MANUAL_DATA = """

DEFAULT_SITE = {
    "title": "온빛 IT 매뉴얼 포털",
    "subtitle": "업무 시스템 사용법을 한 곳에서 확인하세요",
    "imageSize": "m",
}


def _now() -> str:
    return datetime.now(KST).strftime("%Y%m%d-%H%M%S")


def load() -> dict:
    if not DATA.exists():
        return {"site": dict(DEFAULT_SITE), "manuals": []}
    raw = DATA.read_text(encoding="utf-8")
    i = raw.index("{")
    d = json.loads(raw[i:].rstrip().rstrip(";"))
    d.setdefault("site", dict(DEFAULT_SITE))
    d.setdefault("manuals", [])
    return d


def save(data: dict) -> None:
    DATA.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(data, ensure_ascii=False, indent=2)
    DATA.write_text(HEADER + body + ";\n", encoding="utf-8")


def backup() -> str:
    """덮어쓰기 전에 한 벌 떠 둔다.

    PPT 가 원본이라고 정했어도, 사람이 잘못된 파일을 올리는 일은 생긴다.
    그때 되돌릴 수 없으면 매뉴얼 11개가 한 번에 날아간다.
    """
    if not DATA.exists():
        return ""
    BACKUP.mkdir(parents=True, exist_ok=True)
    dst = BACKUP / f"manuals-{_now()}.js"
    shutil.copy2(DATA, dst)

    # 오래된 백업 정리 — 최근 20개만 남긴다
    olds = sorted(BACKUP.glob("manuals-*.js"))
    for p in olds[:-20]:
        p.unlink(missing_ok=True)
    return dst.name


def list_manuals() -> list[dict]:
    d = load()
    return [{"id": m.get("id"), "title": m.get("title"),
             "sections": len(m.get("sections") or []),
             "source": (source_of(m.get("id") or "") or {}).get("name", "")}
            for m in d["manuals"]]


# ── 원본 PPT ─────────────────────────────────────────────────
def save_source(mid: str, filename: str, blob: bytes) -> None:
    """올린 PPT 를 그대로 둔다.

    매뉴얼을 고치려면 원본 PPT 가 있어야 하는데, 그게 만든 사람 PC 에만
    있으면 그 사람이 없을 때 아무도 못 고친다. 파일을 여기 두면
    누구든 내려받아 고쳐서 다시 올릴 수 있다.
    """
    SOURCES.mkdir(parents=True, exist_ok=True)
    for p in SOURCES.glob(f"{mid}.*"):
        p.unlink(missing_ok=True)
    ext = "pptm" if (filename or "").lower().endswith(".pptm") else "pptx"
    (SOURCES / f"{mid}.{ext}").write_bytes(blob)
    (SOURCES / f"{mid}.name").write_text(filename or f"{mid}.{ext}", encoding="utf-8")


def source_of(mid: str) -> dict | None:
    if not mid:
        return None
    for ext in ("pptx", "pptm"):
        p = SOURCES / f"{mid}.{ext}"
        if p.exists():
            named = SOURCES / f"{mid}.name"
            name = named.read_text(encoding="utf-8").strip() if named.exists() else p.name
            return {"path": p, "name": name,
                    "size": p.stat().st_size, "mtime": p.stat().st_mtime}
    return None


def remove(mid: str) -> bool:
    """매뉴얼 하나를 지운다 — 내용·그림·원본 PPT 까지.

    잘못된 이름으로 올려 매뉴얼이 하나 더 생기는 일은 실제로 일어났다.
    지울 방법이 없으면 손으로 manuals.js 를 고치게 되고, 그러면
    이 앱이 관리하는 파일과 사람이 고친 파일이 갈라진다.
    """
    d = load()
    left = [m for m in d["manuals"] if m.get("id") != mid]
    if len(left) == len(d["manuals"]):
        return False
    backup()
    d["manuals"] = left
    save(d)

    folder = IMAGES / mid
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    for p in SOURCES.glob(f"{mid}.*"):
        p.unlink(missing_ok=True)
    return True


_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


def valid_id(mid: str) -> bool:
    """id 는 폴더 이름이 된다. 위로 올라가는 경로가 섞이면 안 된다."""
    return bool(_SAFE_ID.match(mid or ""))


def write_images(mid: str, sections: list[dict]) -> int:
    """슬라이드별 그림을 images/<id>/ 에 저장하고, 상대 경로를 묶음에 달아 준다.

    파일 이름은 **슬라이드 번호**로 짓는다. 항목 번호로 지으면 나중에
    PPT 에서 장을 하나 끼워 넣었을 때 엉뚱한 그림이 남는다.

    그 매뉴얼의 옛 그림은 지운다. PPT 를 통째로 다시 만드는 것이므로
    남겨 두면 아무 데서도 안 쓰이는 파일만 쌓인다.
    """
    folder = IMAGES / mid
    if folder.exists():
        for p in folder.iterdir():
            if p.is_file():
                p.unlink(missing_ok=True)
    folder.mkdir(parents=True, exist_ok=True)

    total = 0
    for sec in sections:
        for blk in sec.get("blocks") or []:
            paths = []
            for k, img in enumerate(blk.get("images") or [], start=1):
                ext = (img["ext"] or "png").lower()
                if ext not in ("png", "jpg", "jpeg", "gif", "webp", "bmp"):
                    ext = "png"
                name = f"{blk['no']:02d}_{k}.{ext}"
                (folder / name).write_bytes(img["bytes"])
                paths.append(f"{mid}/{name}")
                total += 1
            blk["paths"] = paths
    return total


def upsert(mid: str, title: str, icon: str, subtitle: str,
           sections: list[dict], contact_note: str = "") -> str:
    """매뉴얼 하나를 통째로 갈아 끼운다.

    같은 id 가 있으면 **그 자리에서** 바꾼다. 지우고 새로 붙이면
    화면의 매뉴얼 순서가 바뀌어서, 늘 보던 자리에 없다고 헷갈린다.
    """
    d = load()
    entry = {
        "id": mid,
        "icon": icon or (title or mid)[:1],
        "title": title or mid,
        "subtitle": subtitle or "",
        "contactNote": contact_note or "",
        "sections": [
            {"title": s["title"],
             "blocks": [{"steps": b.get("steps") or [],
                         "images": b.get("paths") or []}
                        for b in (s.get("blocks") or [])]}
            for s in sections
        ],
    }

    for n, m in enumerate(d["manuals"]):
        if m.get("id") == mid:
            # PPT 에 맺음말이 없으면, 손으로 적어 둔 문의 안내를 살린다
            entry["contactNote"] = contact_note or m.get("contactNote") or ""
            d["manuals"][n] = entry
            save(d)
            return "replaced"

    d["manuals"].append(entry)
    save(d)
    return "added"
