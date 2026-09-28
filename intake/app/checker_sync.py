"""체험판 검사기(checker.py)를 **회사판과 같은 모양**으로 감싼다.

회사판(app-intake)은 zip 경로를 받아 동기로 돌고 {ok, warn, bad, verdict, report} 를 준다.
체험판은 bytes 를 받아 비동기로 돌고 {sections, tally, raw} 를 준다.
AI 수정·변경 비교 코드는 사내판 것을 그대로 가져다 쓰므로, 여기서 모양만 맞춘다.
판정 이름(ok|warn|bad)은 체험판 것을 그대로 둔다 — db 에 이미 그 말로 쌓여 있다.
(검사하는 규칙 자체는 rules/check-intake.sh 한 벌로 같다.)
"""

from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path

from . import checker

UnsafeZip = checker.BadZip


def _safe_extract(zip_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        checker._safe_extract(zf, dest)


def _app_root(base: Path) -> Path:
    return checker._app_root(base)


def run(zip_path: Path) -> dict:
    """zip 하나를 검사한다 (회사판과 같은 반환 모양)."""
    try:
        got = asyncio.run(checker.run(zip_path.read_bytes(), zip_path.name))
    except checker.BadZip as e:
        return {"verdict": "error", "ok": 0, "warn": 0, "bad": 1, "report": str(e)}
    t = got["tally"]
    return {"ok": t["ok"], "warn": t["warn"], "bad": t["bad"],
            "verdict": got["verdict"], "report": got.get("raw", "")}
