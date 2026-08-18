"""올라온 zip 을 풀어서 check-intake.sh 를 돌리고, 결과를 화면이 쓸 모양으로 바꾼다.

무엇을 하지 않는가 — 이게 더 중요하다
────────────────────────────────────
· **올라온 코드를 실행하지 않는다.** 푸는 것과 읽는 것만 한다.
  남이 만든 앱을 검사하는 도구가 그 앱을 실행하면, 검사가 곧 침입 통로가 된다.
· **서버에 남기지 않는다.** 임시 폴더에 풀고 결과를 낸 뒤 지운다.
  다른 부서 사람이 올린 코드가 우리 디스크에 쌓일 이유가 없다.

점검 규칙은 이 파일에 없다
────────────────────────
저장소 뿌리의 `check-intake.sh` 를 그대로 쓴다. 볼륨으로 붙여 두었으므로
규칙이 바뀌면 이 앱을 다시 빌드하지 않아도 반영된다.
규칙을 두 곳에 두면 반드시 갈라진다 — 화면이 통과라는데 내 PC 에서는 ✗ 가 되는 식으로.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

SCRIPT = Path(os.getenv("CHECK_SCRIPT", "/opt/check-intake.sh"))

# 압축을 푸는 쪽은 늘 조심해야 한다. 셋 다 실제로 있는 공격이다.
MAX_FILES = int(os.getenv("MAX_FILES", "5000"))          # 파일 수
MAX_BYTES = int(os.getenv("MAX_BYTES", str(300 * 1024 * 1024)))   # 푼 뒤 총 크기
TIMEOUT = float(os.getenv("CHECK_TIMEOUT", "120"))       # 검사 시간


class BadZip(Exception):
    """사람에게 그대로 보여 줄 수 있는 말로 던진다."""


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """zip 을 푼다. **경로를 하나씩 확인한다.**

    zip 안의 이름은 `../../etc/passwd` 처럼 적어 넣을 수 있다(zip slip).
    그대로 풀면 목적지 밖에 파일을 쓴다. 파이썬 표준 extractall 도 요즘은
    막아 주지만, 막아 준다는 사실에 기대지 않고 여기서 직접 본다.
    """
    total = 0
    names = zf.infolist()
    if len(names) > MAX_FILES:
        raise BadZip(f"파일이 너무 많습니다 ({len(names)}개). {MAX_FILES}개까지만 받습니다.")
    dest = dest.resolve()
    for info in names:
        if info.is_dir():
            continue
        total += info.file_size
        if total > MAX_BYTES:
            raise BadZip(f"압축을 풀면 너무 커집니다 ({total // 1024 // 1024}MB). "
                         f"{MAX_BYTES // 1024 // 1024}MB까지만 받습니다.")
        target = (dest / info.filename).resolve()
        if not str(target).startswith(str(dest) + os.sep):
            raise BadZip(f"압축 안에 폴더 밖을 가리키는 경로가 있습니다: {info.filename}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out, 1024 * 64)


def _app_root(base: Path) -> Path:
    """진짜 앱 폴더를 찾는다.

    사람들은 두 가지로 압축한다 — 폴더째 넣거나, 폴더 안의 것들을 넣거나.
    앞의 경우 base 밑에 폴더 하나만 덩그러니 있고 그 안에 앱이 있다.
    이걸 안 봐주면 「docker-compose.yml 이 없습니다」만 잔뜩 나온다.
    """
    entries = [p for p in base.iterdir() if not p.name.startswith("__MACOSX")]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return base


LINE = re.compile(r"^\s*([✓△✗·])\s+(.*)$")
SECTION = re.compile(r"^──\s*(.+?)\s*──$")
TALLY = re.compile(r"✓\s*(\d+)\s+△\s*(\d+)\s+✗\s*(\d+)")


def _parse(out: str) -> dict:
    """사람이 읽는 출력을 화면이 쓸 모양으로 바꾼다."""
    sections: list[dict] = []
    tally = {"ok": 0, "warn": 0, "bad": 0}
    for raw in out.splitlines():
        line = raw.rstrip()
        m = SECTION.match(line.strip())
        if m:
            sections.append({"title": m.group(1), "items": []})
            continue
        m = TALLY.search(line)
        if m and "기계가 본 결과" in line:
            tally = {"ok": int(m.group(1)), "warn": int(m.group(2)), "bad": int(m.group(3))}
            continue
        m = LINE.match(line)
        if m and sections:
            mark = {"✓": "ok", "△": "warn", "✗": "bad", "·": "note"}[m.group(1)]
            sections[-1]["items"].append({"mark": mark, "text": m.group(2)})
    # ★ 빈 절은 버린다.
    #   check-intake 는 끝에 「여기서부터는 사람이 봐야 합니다」를 번호 목록으로
    #   찍는데, ✓△✗ 가 아니라서 여기서는 항목이 하나도 안 잡힌다. 그대로 두면
    #   화면에 제목만 덩그러니 남는다. 그 내용은 화면이 따로 들고 있다.
    sections = [s for s in sections if s["items"]]
    return {"sections": sections, "tally": tally,
            "verdict": "bad" if tally["bad"] else ("warn" if tally["warn"] else "ok")}


async def run(zip_bytes: bytes, filename: str) -> dict:
    """zip 하나를 점검한다. 임시 폴더는 어떤 경우에도 지운다."""
    if not SCRIPT.exists():
        raise BadZip(f"점검 규칙 파일이 없습니다 ({SCRIPT}). 담당자에게 알려 주세요.")

    tmp = Path(tempfile.mkdtemp(prefix="intake-"))
    try:
        try:
            with zipfile.ZipFile(__import__("io").BytesIO(zip_bytes)) as zf:
                _safe_extract(zf, tmp)
        except zipfile.BadZipFile:
            raise BadZip("zip 파일이 아니거나 깨져 있습니다.") from None

        root = _app_root(tmp)
        proc = await asyncio.create_subprocess_exec(
            "bash", str(SCRIPT), str(root),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            cwd=str(SCRIPT.parent),   # 스크립트가 옆의 portal/.env 를 찾는다. 없으면 그 검사만 건너뛴다.
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            raise BadZip(f"점검이 {int(TIMEOUT)}초를 넘겼습니다. 파일이 너무 많은 것 같습니다.") from None

        text = out.decode("utf-8", "replace")
        result = _parse(text)
        result["name"] = root.name if root is not tmp else Path(filename).stem
        result["raw"] = text
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
