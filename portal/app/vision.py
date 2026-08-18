"""그림에서 글자를 읽는다.

### OCR 엔진을 쓰지 않는 이유

이미지를 읽는 흔한 방법은 Tesseract 같은 OCR 엔진을 설치하는 것이다.
그 길을 택하지 않았다.

  - 컨테이너 이미지가 50MB 가까이 늘어난다 (한국어 학습 자료 포함)
  - 사진·기울어진 스캔에서 한국어 정확도가 들쭉날쭉하다
  - 표가 있으면 순서가 뒤엉킨다

대신 **이미 쓰고 있는 게이트웨이**에 그림을 그대로 넘긴다.
설치할 것이 없고, 표가 있어도 사람이 읽는 순서로 나온다.

실제로 확인한 결과 (check_vision.py):

    openai/gpt-5-mini             5/5 맞음 · 4.4초 · 입력 316 토큰
    google/gemini-3.5-flash-lite  5/5 맞음 · 1.4초 · 입력 1135 토큰

### 여기서는 읽기만 한다

이 파일은 그림을 **글자로 바꿔 줄 뿐**이다. 요약하거나 판단하는 일은
챗이 쓰는 모델이 한다. filetext.py 가 PDF·엑셀에 대해 하는 일과 같다.
글자를 뽑는 방법만 다르다.

그래서 여기서 부르는 모델은 챗 모델과 **달라도 된다.** 읽기만 하면
되므로 싸고 빠른 것으로 충분하다. `VISION_MODEL` 로 따로 지정한다.

### 알아둘 것 — 그림이 밖으로 나간다

문서 글자를 넘기는 것과 같은 성격이지만, 그림은 더 많이 담긴다.
명함·신분증·화이트보드 사진이 통째로 공급자에게 간다.

  - `VISION=off` 로 끌 수 있다 (끄면 예전처럼 "이미지는 읽지 못합니다")
  - 누가 몇 장을 읽혔는지 이력에 남는다 (파일 이름은 남기지 않는다)
  - 사람 얼굴·신원을 판별하는 요청은 하지 않는다. 글자만 옮긴다
"""

import base64
import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

ENABLED = os.environ.get("VISION", "on").strip().lower() in ("on", "1", "true", "yes")

# 읽기 전용이라 챗 모델과 같을 필요가 없다. 비워 두면 MODEL 을 그대로 쓴다.
MODEL = (os.environ.get("VISION_MODEL") or os.environ.get("MODEL") or "").strip()

BASE = (os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
KEY = os.environ.get("OPENAI_API_KEY", "")

# 큰 사진은 토큰이 그만큼 든다. 넘으면 줄여서 다시 올려 달라고 말한다.
# (줄여 주는 기능을 넣으려면 Pillow 가 필요한데, 그 무게를 지는 대신
#  "줄여서 올려주세요" 한 줄로 끝내는 편이 낫다고 보았다.)
MAX_MB = float(os.environ.get("VISION_MAX_MB", "8"))

# 스캔한 PDF 를 읽을 때 최대 몇 쪽까지 볼지. 쪽수만큼 비용이 는다.
MAX_PAGES = int(os.environ.get("VISION_MAX_PAGES", "5"))

# 문서(엑셀·워드·장표) 안에 붙어 있는 그림을 최대 몇 장까지 읽을지.
# 장표 30장짜리를 통째로 읽으면 그만큼 돈이 나간다. 넘으면 몇 장을
# 못 봤는지 답변에 적어 준다. 조용히 자르면 다 읽은 줄 안다.
MAX_IMAGES = int(os.environ.get("VISION_MAX_IMAGES", "5"))

TIMEOUT = int(os.environ.get("VISION_TIMEOUT", "120"))

_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
         "gif": "image/gif", "webp": "image/webp"}

# 무엇을 시킬지. "요약해라" 가 아니라 "옮겨 적어라" 다.
# 판단은 챗 모델이 한다. 여기서 해석하면 두 번 해석되어 원문이 흐려진다.
ASK = (
    "이 그림에 보이는 글자를 **그대로 옮겨 적어라.**\n"
    "  - 요약하거나 고쳐 쓰지 마라. 적힌 순서대로 옮긴다.\n"
    "  - 표는 각 줄을 ' | ' 로 구분해서 옮긴다.\n"
    "  - 흐려서 확실하지 않은 글자는 그 자리에 (?) 를 적는다. 지어내지 마라.\n"
    "  - 글자가 없는 그림이면, 무엇이 담긴 그림인지 한 줄로만 적는다.\n"
    "  - 사람의 얼굴이나 신원은 판별하지 마라."
)


class VisionError(Exception):
    """직원에게 그대로 보여줄 수 있는 실패 사유."""


def available() -> tuple[bool, str]:
    """쓸 수 있는 상태인지. (가능한가, 안 되면 이유)"""
    if not ENABLED:
        return False, "이미지 읽기 기능이 꺼져 있습니다. (VISION=off)"
    if not KEY:
        return False, "AI 공급자 키가 설정되어 있지 않습니다. IT 담당자에게 문의해주세요."
    if not MODEL:
        return False, "읽기에 쓸 모델이 지정되어 있지 않습니다. (VISION_MODEL)"
    return True, ""


def _data_uri(blob: bytes, ext: str) -> str:
    mime = _MIME.get((ext or "").lower().lstrip("."), "image/png")
    return f"data:{mime};base64," + base64.b64encode(blob).decode()


def read_images(images: list[tuple[bytes, str]], hint: str = "",
                user_id: str = "") -> str:
    """그림 여러 장을 한 번에 넘기고 글자를 받는다.

    스캔한 PDF 는 쪽마다 그림이 하나씩 나오므로 여러 장이 된다.
    한 번에 보내야 앞뒤 문맥이 이어진다.
    """
    ok, why = available()
    if not ok:
        raise VisionError(why)
    if not images:
        raise VisionError("읽을 그림이 없습니다.")

    total = sum(len(b) for b, _ in images)
    if total > MAX_MB * 1024 * 1024:
        # 1MB 미만을 "0.0MB" 로 보여주면 왜 거절당했는지 알 수 없다
        how_big = (f"{total / 1048576:.1f}MB" if total >= 1048576
                   else f"{total / 1024:.0f}KB")
        raise VisionError(
            f"그림이 너무 큽니다 ({how_big}). "
            f"{MAX_MB:g}MB 아래로 줄여서 다시 올려주세요."
        )

    content: list[dict] = [{"type": "text", "text": ASK + (f"\n\n{hint}" if hint else "")}]
    for blob, ext in images:
        content.append({"type": "image_url",
                        "image_url": {"url": _data_uri(blob, ext)}})

    body = {"model": MODEL, "messages": [{"role": "user", "content": content}]}
    req = urllib.request.Request(
        BASE + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + KEY,
                 "Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        log.warning("이미지 읽기 실패 %s %s", e.code, detail)
        if e.code in (400, 404, 415, 422):
            # 모델이 그림을 안 받는 경우가 여기로 온다.
            raise VisionError(
                "지금 지정된 모델이 그림을 받지 못합니다. "
                "IT 담당자에게 문의해주세요. (VISION_MODEL)"
            )
        raise VisionError("그림을 읽지 못했습니다. 잠시 뒤 다시 시도해 주세요.")
    except Exception as e:  # noqa: BLE001
        log.warning("이미지 읽기 실패 %s", e)
        raise VisionError("그림을 읽지 못했습니다. 잠시 뒤 다시 시도해 주세요.")

    # 그림은 한 장에 수백~수천 토큰이다. 엑셀 하나 열었을 뿐인데
    # 안에 붙은 캡처 다섯 장 값이 나가는 일이 여기서 생긴다. 반드시 남긴다.
    u = data.get("usage") or {}
    from . import usage as _usage
    _usage.record("그림", MODEL,
                  int(u.get("prompt_tokens") or 0),
                  int(u.get("completion_tokens") or 0),
                  user_id=user_id, images=len(images))

    try:
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except Exception:  # noqa: BLE001
        raise VisionError("그림을 읽지 못했습니다. 응답 형식이 예상과 다릅니다.")

    if not text:
        raise VisionError(
            "이 그림에서는 아무것도 읽어내지 못했습니다. "
            "글자가 잘 보이는 사진으로 다시 올려주세요."
        )
    return text


def read_image(blob: bytes, ext: str, user_id: str = "") -> str:
    return read_images([(blob, ext)], user_id=user_id)
