"""붙인 파일 읽기 — 전용 앱이 없을 때 쓰는 길.

### 언제 쓰이나

    이력서 → 이력서 분석 앱이 있으면 그쪽 도구가 불린다 (점수·기록이 남는다)
    청구서 → 그런 앱이 없다. 이 도구가 글자를 뽑아 모델에게 넘긴다

전용 앱이 있는 쪽이 항상 낫다. 그 앱은 자기 기준으로 판단하고, 결과를
화면에 남기고, 담당자가 다시 볼 수 있다. 이 도구는 **그런 앱이 없을 때**
"그래도 이거 한 번 봐줘" 를 할 수 있게 하는 것이다.

### 글자를 얻는 두 가지 길

    문서 (pdf·docx·xlsx·pptx·html…)  →  filetext.py 가 글자를 뽑는다
    사진·스캔한 PDF                   →  vision.py 가 그림을 보고 옮겨 적는다

어느 길로 갈지는 이 파일이 정한다. filetext 가 `NeedsVision` 을 올리면
"글자로는 안 되고 그림으로 봐야 한다"는 뜻이므로 vision 으로 넘긴다.
스캔한 PDF 는 쪽마다 사진 한 장을 꺼내서 한꺼번에 보낸다.

챗을 쓰는 사람 입장에서는 구분이 없다. 붙이고 "이거 요약해줘" 하면 된다.

### 알아둘 것 — 내용이 밖으로 나간다

이 도구는 뽑아낸 글자를, 사진이면 **사진 자체를** AI 공급자(비즈라우터 등)로
보낸다. 지금까지 포털이 하던 일(앱에 물어보고 답을 옮기기)과 성격이 다르다.
그래서

  - 문서 읽기는 `FILE_READ=off`, 그림 읽기는 `VISION=off` 로 각각 끌 수 있다
  - 누가 어떤 형식을 읽혔는지 이력에 남는다 (파일 이름은 남기지 않는다)
  - 도구 설명에 "전용 서비스가 있으면 그쪽을 쓰라"고 적어 두었다

민감한 문서를 다루는 업무라면 전용 앱을 만드는 편이 맞다.

### 모델

문서 글자에 대한 판단은 **지금 챗이 쓰는 모델**이 한다. 이 도구는 글자만
넘긴다. 그림을 옮겨 적는 일만 `VISION_MODEL` 이 맡는데, 이것도 읽기만
하므로 싸고 빠른 것으로 충분하다. 둘 다 `.env` 에서 바꾸면 그대로 반영된다.
도구 코드는 손댈 것이 없다.
"""

import os

from .. import filetext, memory, uploads, vision
from ..registry import User, tool
from ..schemas import ToolResult, fail

ENABLED = os.environ.get("FILE_READ", "on").strip().lower() in ("on", "1", "true", "yes")


@tool(
    name="read_attached_file",
    label="첨부 파일 읽기",
    description=(
        "챗에 첨부된 파일의 내용을 읽어온다. "
        "'이거 요약해줘', '이 문서 정리해줘', '여기 금액 얼마야', "
        "'이 사진에 뭐라고 적혀 있어', '무슨 내용인지 알려줘' 처럼 "
        "**파일이 첨부된 상태에서** 그 내용을 봐야 답할 수 있을 때 쓴다. "
        "읽을 수 있는 것: 문서(pdf, docx, xlsx, pptx, html, csv, txt, md, json)와 "
        "사진·화면 캡처(png, jpg)와 스캔한 PDF. "
        "엑셀·워드·장표 안에 **붙여 넣은 그림**(화면 캡처 등)도 함께 읽는다. "
        "한글(.hwp)·옛 오피스 형식(.doc/.xls/.ppt)은 읽지 못하며, "
        "그 경우 이유를 돌려준다. "
        "※ 그 파일을 다루는 전용 서비스 도구가 따로 있으면 그쪽을 먼저 쓴다. "
        "이 도구는 전용 서비스가 없을 때 쓰는 일반적인 방법이다."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "파일의 file_id. [이 대화에 올라온 파일] 목록에 적혀 있다. 그 값을 그대로 쓴다.",
            },
        },
        "required": ["file_id"],
    },
    # service 를 지정하지 않는다 = 로그인한 사람 누구나.
    # 자기가 올린 파일만 읽히므로 남의 자료가 새지 않는다.
)
def read_attached_file(user: User, file_id: str) -> ToolResult:
    if not ENABLED:
        return fail("첨부 파일 읽기 기능이 꺼져 있습니다. IT 담당자에게 문의해주세요.")

    # 본인이 올린 파일만 나온다 (uploads.get 이 판정한다)
    got = uploads.read(file_id, user.user_id)
    if not got:
        return fail("첨부한 파일을 찾지 못했습니다. 파일을 다시 올려주세요.")
    meta, blob = got
    if meta["user_id"] != user.user_id:
        # 열람자 권한으로 남의 파일을 챗에 끌어오는 것은 막는다.
        # 그건 화면에서 확인할 일이지 챗이 할 일이 아니다.
        return fail("본인이 올린 파일만 읽을 수 있습니다.")

    ext = (meta["ext"] or "").lower()
    how = "글자"          # 이력에 남길 때 어느 길로 읽었는지 구분한다

    # 전에 읽어 둔 것이 있으면 그대로 쓴다.
    # 대화가 이어지면 같은 파일을 여러 번 읽게 되는데, 파일은 바뀌지 않는다.
    # 그림이 든 문서를 매번 다시 읽으면 그때마다 공급자에 돈이 나간다.
    cached = uploads.get_text(file_id)
    if cached:
        text, how, cut = cached[0], cached[1], cached[2]
        return _result(meta, ext, text, how, cut)

    try:
        text, cut = filetext.extract(ext, blob)
        # 엑셀·워드·장표 안에 **붙여 넣은 그림**이 있으면 그것도 읽는다.
        # 사내 문서는 셀에 제목만 있고 숫자는 캡처 그림 안에 있는 경우가 흔하다.
        shots, more = _embedded(ext, blob, user.user_id)
        if shots:
            text = (text + "\n\n" + shots).strip()
            how = "글자+그림"
            # cut(잘림)은 건드리지 않는다. 그림을 다 못 본 것과 글자가
            # 중간에서 끊긴 것은 다른 일이고, 몇 장을 못 봤는지는
            # 본문 머리말에 이미 적혀 있다.
            _ = more
    except filetext.NeedsVision as e:
        # 글자로는 안 된다. 그림으로 본다.
        try:
            text, cut = _by_vision(ext, blob, str(e), user.user_id)
            how = "그림"
        except vision.VisionError as ve:
            return fail(str(ve))
        except filetext.ExtractError as fe:
            return fail(str(fe))
    except filetext.ExtractError as e:
        # 왜 못 읽는지를 그대로 전한다. "실패했습니다" 로 뭉개면
        # 사용자가 무엇을 고쳐야 할지 알 수 없다.
        return fail(str(e))
    except Exception as e:  # noqa: BLE001
        return fail(f"파일을 읽지 못했습니다. {type(e).__name__}")

    # 파일 이름은 남기지 않는다. 이름만으로도 개인정보가 드러난다.
    memory.log_action(user.user_id, "첨부 파일 읽기",
                      f"{ext} · {how} · {len(text)}자", service="포털")
    uploads.put_text(file_id, text, how, cut)

    return _result(meta, ext, text, how, cut)


def _result(meta: dict, ext: str, text: str, how: str, cut: bool) -> ToolResult:
    return ToolResult(
        summary=(f"{meta['name']} 에서 {len(text)}자를 읽었습니다."
                 + (" (사진을 보고 옮겨 적었습니다)" if how == "그림" else "")
                 + (" (안에 붙어 있는 그림까지 읽었습니다)" if how == "글자+그림" else "")
                 + (" (앞부분만)" if cut else "")),
        data={
            "파일명": meta["name"],
            "형식": ext,
            "읽은 방법": {
                "그림": "사진을 보고 옮겨 적음",
                "글자+그림": "문서 글자 + 안에 붙어 있는 그림까지 읽음",
            }.get(how, "문서에서 글자를 뽑음"),
            "내용": text,
        },
        truncated=cut,
    )


def _embedded(ext: str, blob: bytes, user_id: str = "") -> tuple[str, bool]:
    """문서 안에 붙여 넣은 그림을 읽어 글자로 돌려준다. (글자, 못 본 게 있나)

    실패해도 문서 글자는 이미 있으므로 조용히 넘어간다. 그림을 못 읽었다고
    문서 읽기 전체를 실패로 만들 이유가 없다.
    """
    ok, _ = vision.available()
    if not ok:
        return "", False
    try:
        shots, total = filetext.office_images(ext, blob, vision.MAX_IMAGES)
    except Exception:  # noqa: BLE001
        return "", False
    if not shots:
        return "", False

    try:
        read = vision.read_images(
            shots,
            hint=(f"이 그림들은 문서 안에 붙여 넣은 {len(shots)}장이다. "
                  f"순서대로 옮겨 적어라."),
            user_id=user_id,
        )
    except vision.VisionError:
        return "", False

    head = f"[문서 안에 붙어 있는 그림 {len(shots)}장을 읽은 내용]"
    if total > len(shots):
        head += f" (전체 {total}장 중 앞 {len(shots)}장만 읽었습니다)"
    return f"{head}\n{read}", total > len(shots)


def _by_vision(ext: str, blob: bytes, why: str, user_id: str = "") -> tuple[str, bool]:
    """그림으로 읽는다. (글자, 잘렸는지)

    why 는 filetext 가 올린 이유다. 그림 읽기를 쓸 수 없을 때
    그 이유를 그대로 보여줘야 예전과 같은 안내가 나온다.
    """
    ok, reason = vision.available()
    if not ok:
        # "이미지는 글자를 직접 뽑을 수 없습니다" + "기능이 꺼져 있습니다"
        raise vision.VisionError(f"{why} {reason}")

    if ext in filetext.IMAGE_EXTS:
        images = [(blob, ext)]
        note = ""
    else:
        # 스캔한 PDF — 쪽마다 사진을 꺼낸다
        images = filetext.pdf_images(blob, vision.MAX_PAGES)
        if not images:
            raise vision.VisionError(
                f"{why} (안에 든 사진을 꺼내지 못했습니다. "
                f"사진을 png 나 jpg 로 저장해서 올리시면 읽을 수 있습니다.)"
            )
        note = f"이 그림들은 스캔한 PDF 의 {len(images)}쪽이다. 쪽 순서대로 옮겨 적어라."

    text = vision.read_images(images, hint=note, user_id=user_id)

    # 문서 쪽과 같은 한도를 적용한다. 여기만 무제한이면 비용이 새어 나간다.
    if len(text) > filetext.MAX_CHARS:
        return text[:filetext.MAX_CHARS], True
    return text, False
