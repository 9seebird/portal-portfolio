# -*- coding: utf-8 -*-
"""체험판 회사의 **이름 한 곳**.

    python tools/company.py --check      낡은 이름이 남아 있는지 본다 (CI 가 부른다)
    python tools/company.py --apply      아래 상수대로 저장소 전체를 맞춘다
    python tools/company.py --wordmark   로고 그림만 다시 그린다

────────────────────────────────────────────────────────────
왜 이 파일이 생겼나

처음에는 회사 이름을 `demo_company.py` 상수로만 두었다. 그런데 화면(HTML)
에는 상수를 가져다 쓸 방법이 없어서 글자를 그대로 박아 넣었고, README ·
nginx 주석 · 예제 메일 주소까지 퍼져서 **한 이름이 84군데**에 남았다.

그러다 지어낸 줄 알았던 이름이 **실제로 있는 회사**인 것을 알게 됐다.
바꾸려고 보니 84군데를 손으로 고쳐야 했고, 하나라도 빠뜨리면 화면마다
회사 이름이 다르게 보이는 상태가 된다.

그래서 이름을 여기 한 곳에 두고, 저장소를 여기에 맞추는 일을 스크립트가
하게 했다. 다음에 또 바꿀 일이 생기면 **아래 세 줄만 고치고 --apply** 다.

────────────────────────────────────────────────────────────
전부 지어낸 것이다. 실제 회사·사람·금액과 아무 관계가 없다.
도메인은 문서용으로 예약된 example.com 아래만 쓴다 (RFC 2606).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# ── 여기가 전부다 ────────────────────────────────────────────
COMPANY = "온빛"
COMPANY_EN = "ONBIT"
DOMAIN = "onbit.example.com"

# 로고에 쓰는 두 낱말. 앞은 진한 색, 뒤는 강조 색으로 그린다.
WORDMARK = ("ONBIT", "PORTAL")

# ── 예전에 쓰던 이름 ────────────────────────────────────────
# 이름을 바꿀 때마다 옛 값을 여기에 **덧붙인다.** 지우지 않는다.
#   · --apply 는 이 낱말들을 지금 값으로 바꾼다
#   · --check 는 이 낱말이 하나라도 남아 있으면 실패한다
#     (옛 코드 조각을 붙여 넣었을 때 조용히 되살아나는 것을 막는다)
RETIRED = [
    # (한글, 영문, 도메인 앞부분)
    ("누리코스메틱", "NURI COSMETIC", "nuricos"),
]

# ── 로고 색 ─────────────────────────────────────────────────
# 밝은 배경용 / 어두운 배경용. 원래 그림에서 뽑은 값 그대로다.
WORDMARK_STYLE = {
    "light": {"ink": (24, 30, 40), "accent": (31, 78, 121)},
    "dark":  {"ink": (236, 236, 239), "accent": (122, 172, 220)},
}
WORDMARK_SIZE = (867, 85)          # 화면 CSS 가 이 비율을 전제로 한다
WORDMARK_DIR = Path(__file__).resolve().parents[1] / "portal" / "static"

ROOT = Path(__file__).resolve().parents[1]

# 글자를 바꾸면 안 되는 것들. 그림·압축파일에 문자열 치환을 들이대면 깨진다.
SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip",
               ".xlsx", ".xls", ".pptx", ".docx", ".db", ".sqlite",
               ".woff", ".woff2", ".ttf", ".pyc", ".tgz", ".gz"}


def _tracked() -> list[Path]:
    """깃이 아는 파일만 본다. data/ 나 캐시까지 훑으면 오래 걸리고 뜻도 없다."""
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--cached", "--others",
         "--exclude-standard"],
        capture_output=True, text=True, encoding="utf-8")
    me = Path(__file__).resolve()
    files = []
    for line in out.stdout.splitlines():
        p = ROOT / line.strip()
        if p.suffix.lower() in SKIP_SUFFIX or not p.is_file():
            continue
        # ★ 자기 자신은 건드리지 않는다.
        #   RETIRED 목록에 옛 이름이 적혀 있으므로, 빼지 않으면
        #   --check 는 자기 목록을 보고 실패하고
        #   --apply 는 그 목록을 지금 이름으로 덮어써 기록을 없앤다.
        if p.resolve() == me:
            continue
        files.append(p)
    return files


def _pairs() -> list[tuple[str, str]]:
    """옛 낱말 → 지금 낱말. 긴 것부터 바꿔야 겹치는 경우에 안 깨진다."""
    out = []
    for ko, en, dom in RETIRED:
        out += [(en, COMPANY_EN), (ko, COMPANY), (dom, DOMAIN.split(".")[0])]
    return sorted(out, key=lambda x: -len(x[0]))


def check() -> int:
    bad = []
    words = [w for tri in RETIRED for w in tri]
    pat = re.compile("|".join(re.escape(w) for w in words))
    for p in _tracked():
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            m = pat.search(line)
            if m:
                bad.append(f"  {p.relative_to(ROOT)}:{i}: {m.group(0)}")
    if bad:
        print(f"✗ 예전 회사 이름이 {len(bad)}군데 남아 있습니다:")
        print("\n".join(bad[:30]))
        if len(bad) > 30:
            print(f"  … 그리고 {len(bad) - 30}군데 더")
        print("\n  → python tools/company.py --apply 로 한 번에 고칩니다.")
        return 1
    print(f"✓ 회사 이름이 「{COMPANY} / {COMPANY_EN} / {DOMAIN}」 하나로 맞습니다.")
    return 0


def apply() -> int:
    pairs = _pairs()
    changed = 0
    for p in _tracked():
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new = text
        for old, now in pairs:
            new = new.replace(old, now)
        if new != text:
            p.write_text(new, encoding="utf-8")
            print(f"  고침 {p.relative_to(ROOT)}")
            changed += 1
    print(f"✓ {changed}개 파일을 고쳤습니다.")
    return wordmark()


def wordmark() -> int:
    """로고 그림을 다시 그린다.

    이름을 글자로만 바꾸면 화면 왼쪽 위 로고는 **옛 이름 그대로 남는다** —
    그건 글자가 아니라 그림이기 때문이다. 실제로 그걸 놓칠 뻔했다.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("  △ Pillow 가 없어 로고는 건너뜁니다  (pip install pillow)")
        return 0

    font_path = None
    for cand in ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "C:/Windows/Fonts/arialbd.ttf"):
        if Path(cand).exists():
            font_path = cand
            break
    if not font_path:
        print("  △ 굵은 산세리프 글꼴을 못 찾아 로고는 건너뜁니다.")
        return 0

    W, H = WORDMARK_SIZE
    PAD, GAP, STROKE = 14, 26, 3      # STROKE 로 굵기를 더한다 (블랙 웨이트 흉내)
    w1, w2 = WORDMARK

    # 두 낱말이 폭에 딱 맞도록 글자 크기를 찾는다.
    size = H
    while size > 8:
        f = ImageFont.truetype(font_path, size)
        probe = Image.new("RGBA", (1, 1))
        d = ImageDraw.Draw(probe)
        a = d.textbbox((0, 0), w1, font=f, stroke_width=STROKE)
        b = d.textbbox((0, 0), w2, font=f, stroke_width=STROKE)
        total = (a[2] - a[0]) + GAP + (b[2] - b[0])
        if total <= W - PAD * 2 and (a[3] - a[1]) <= H - 12:
            break
        size -= 1

    for kind, style in WORDMARK_STYLE.items():
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        a = d.textbbox((0, 0), w1, font=f, stroke_width=STROKE)
        b = d.textbbox((0, 0), w2, font=f, stroke_width=STROKE)
        wa, wb = a[2] - a[0], b[2] - b[0]
        x = (W - (wa + GAP + wb)) // 2
        y = (H - (a[3] - a[1])) // 2 - a[1]
        d.text((x - a[0], y), w1, font=f, fill=style["ink"],
               stroke_width=STROKE, stroke_fill=style["ink"])
        d.text((x + wa + GAP - b[0], y), w2, font=f, fill=style["accent"],
               stroke_width=STROKE, stroke_fill=style["accent"])
        out = WORDMARK_DIR / f"wordmark-{kind}.png"
        im.save(out)
        print(f"  로고 {out.relative_to(ROOT)}  ({w1} {w2}, {size}px)")
    return 0


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--check"
    if arg == "--check":
        sys.exit(check())
    if arg == "--apply":
        sys.exit(apply())
    if arg == "--wordmark":
        sys.exit(wordmark())
    print(__doc__)
    sys.exit(2)
