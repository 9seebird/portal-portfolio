"""반려 사유를 **그대로 붙여넣을 수 있는 프롬프트**로 바꾼다.

검사 결과를 받은 사람은 대개 비개발자다. "portal-net 설정이 없습니다" 만
보여 주면 무엇을 어떻게 고쳐야 하는지 알 수 없다. 그래서 지적 하나마다
**무엇을 · 왜 · 어떻게** 를 붙이고, 만들 때 쓰던 도구(웍스AI 등)에 그대로
넣을 수 있는 한 덩어리로 묶어 준다.

여기 적힌 고치는 법은 check-intake.sh 가 보는 것과 짝이다. 규칙이 바뀌면
이 표도 같이 손봐야 한다 — 그래서 한 파일에 몰아 두었다.
"""

from __future__ import annotations

import re

# (검사 메시지에서 찾을 조각, 제목, 왜, 어떻게)
RULES: list[tuple[str, str, str, str]] = [
    ("docker-compose.yml 가 없습니다",
     "docker-compose.yml 만들기",
     "이 파일이 있어야 사내 서버가 앱을 띄울 수 있습니다.",
     """프로젝트 맨 위에 docker-compose.yml 을 아래 모양으로 만들어 주세요.
services 이름과 container_name 은 서비스 ID 와 같게 씁니다.

```yaml
services:
  {sid}:
    build: .
    container_name: {sid}
    restart: unless-stopped
    env_file: [.env]
    expose: ["8080"]          # ports 는 절대 쓰지 않습니다
    volumes:
      - ./data:/data          # 저장하는 것이 있으면 꼭 둡니다
    networks: [portal-net]
networks:
  portal-net:
    external: true
```"""),

    ("portal-net 설정이 없습니다",
     "portal-net 에 붙이기",
     "포털이 이 앱을 이름으로 찾습니다. 이게 없으면 주소를 열어도 502 가 납니다.",
     """docker-compose.yml 의 서비스 아래에 networks 를 넣고, 파일 맨 아래에
external 선언을 넣어 주세요.

```yaml
    networks: [portal-net]
networks:
  portal-net:
    external: true
```"""),

    ("external: true 가 없습니다",
     "portal-net 을 external 로 선언하기",
     "이 그물망은 포털이 미리 만들어 둔 것입니다. 앱이 새로 만들면 안 됩니다.",
     """docker-compose.yml 맨 아래에 이렇게 적어 주세요.

```yaml
networks:
  portal-net:
    external: true
```"""),

    ("container_name 이 없습니다",
     "container_name 정하기",
     "포털이 컨테이너 이름으로 앱을 부릅니다. 이름이 없으면 못 찾습니다.",
     """docker-compose.yml 의 서비스 아래에 넣어 주세요. 서비스 ID 와 같게 씁니다.

```yaml
    container_name: {sid}
```"""),

    ("ports 가 있습니다",
     "바깥 포트 없애기",
     "사내 앱은 포털을 거쳐서만 들어옵니다. 포트를 직접 열면 포털을 건너뛰고 "
     "들어올 수 있게 되어 규칙 위반입니다.",
     """docker-compose.yml 에서 ports: 줄을 통째로 지우고 expose 로 바꿔 주세요.

```yaml
    expose: ["8080"]
```"""),

    ("compose 에 build 가 있는데 Dockerfile 이 없습니다",
     "Dockerfile 만들기",
     "build: . 라고 적어 두면 도커가 Dockerfile 을 찾습니다.",
     """프로젝트 맨 위에 Dockerfile 을 만들어 주세요. 베이스 이미지는
python:3.13-slim 으로 **버전을 붙여** 고정합니다.

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8080
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8080"]
```"""),

    ("떠다니는 태그입니다",
     "베이스 이미지 버전 고정하기",
     "latest 나 태그 없는 이미지는 어제와 오늘이 다른 앱이 됩니다. "
     "어제 되던 것이 오늘 안 되는 가장 흔한 원인입니다.",
     """Dockerfile 의 FROM 줄에 버전을 붙여 주세요.

```dockerfile
FROM python:3.13-slim
```"""),

    ("태그가 없습니다",
     "베이스 이미지 버전 고정하기",
     "태그가 없으면 latest 와 같습니다. 어제와 오늘이 다른 앱이 됩니다.",
     """Dockerfile 의 FROM 줄에 버전을 붙여 주세요.

```dockerfile
FROM python:3.13-slim
```"""),

    ("규칙 14 는 python:3.13-slim",
     "베이스 이미지를 회사 표준으로",
     "회사 표준은 python:3.13-slim 입니다. 다른 것을 쓰면 서버에서 동작이 달라질 수 있습니다.",
     """Dockerfile 의 FROM 줄을 바꿔 주세요.

```dockerfile
FROM python:3.13-slim
```"""),

    ("포털 자동 등록이 없습니다",
     "뜰 때 포털에 자기를 등록하기",
     "이게 없으면 앱은 돌지만 포털 관리자 화면에 나타나지 않아서, "
     "권한을 줄 수도 없고 아무도 못 찾습니다.",
     """앱이 시작할 때 포털에 한 번 알리게 해 주세요.

```python
import os, httpx
from fastapi import FastAPI

app = FastAPI()
PORTAL = os.getenv("PORTAL_API_URL", "")

@app.on_event("startup")
async def register():
    if not PORTAL:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(f"{PORTAL}/api/services/register",
                         json={{"id": "{sid}", "name": "{title}", "path": "/{sid}/"}})
    except Exception:
        pass          # 포털이 아직 안 떠 있어도 앱은 떠야 합니다
```"""),

    (".env 가 딸려 왔습니다",
     ".env 를 빼고 다시 압축하기",
     "**가장 급한 것입니다.** .env 에는 만드신 분의 비밀번호와 토큰이 들어 있습니다. "
     "그대로 넘어왔습니다.",
     """1. 보낸 zip 에서 .env 파일을 지우고 다시 압축해 주세요.
2. .gitignore 에 `.env` 를 넣어 주세요.
3. 그 안에 있던 **비밀번호·토큰은 이미 노출된 것으로 보고 새로 발급**해 주세요.
4. 대신 .env.example 에는 값 없이 이름만 적습니다.

```
DEV_MODE=false
PORTAL_API_URL=http://portal:8080
AUDIT_TOKEN=
```"""),

    ("비밀번호·토큰처럼 보이는 글자가 박혀 있습니다",
     "코드에 박힌 비밀값 빼내기",
     "코드 안에 비밀번호나 키를 직접 적으면 깃에 그대로 올라갑니다.",
     """코드에서 지우고 환경변수로 읽게 바꿔 주세요.

```python
import os
API_KEY = os.getenv("API_KEY", "")     # 코드에는 값을 적지 않습니다
```

이름만 .env.example 에 적고, 실제 값은 담당자에게 따로 알려 주세요."""),

    (".gitignore 에 .env 가 없습니다",
     ".gitignore 에 .env 넣기",
     "빠져 있으면 다음에 비밀번호가 통째로 깃에 올라갑니다.",
     """.gitignore 에 아래 줄을 넣어 주세요.

```
.env
```"""),

    (".gitignore 에 data/ 가 없습니다",
     ".gitignore 에 data/ 넣기",
     "data 폴더에는 실제 업무 자료가 쌓입니다. 깃에 올라가면 안 됩니다.",
     """.gitignore 에 아래 줄을 넣어 주세요.

```
data/
```"""),

    ("화면이 슬래시로 시작하는 주소로 API 를 부릅니다",
     "API 주소를 상대경로로 바꾸기",
     "이 앱은 포털 아래 /{sid}/ 경로에 붙습니다. `/api/...` 로 부르면 "
     "포털 맨 위를 찾아가서 404 가 납니다.",
     """화면(HTML/JS)에서 fetch 주소 앞의 슬래시를 떼 주세요.

```javascript
// 이렇게 하지 마세요
fetch('/api/items')

// 이렇게 해 주세요
fetch('api/items')
```"""),

    ("화면이 바깥 인터넷 주소를 부릅니다",
     "바깥 인터넷 주소 없애기",
     "사내망에서는 바깥이 막혀 있습니다. 화면만 뜨고 아무것도 안 도는 앱이 됩니다.",
     """cdn.jsdelivr.net, unpkg.com, fonts.googleapis.com 같은 주소를 쓰고 있다면
그 파일을 프로젝트 안에 내려받아 넣고 그 경로를 부르도록 바꿔 주세요."""),

    ("DEV_MODE 처리가 안 보입니다",
     "DEV_MODE 넣기",
     "만드신 분이 혼자 돌려볼 때 쓰는 장치입니다. 포털 없이도 화면이 열립니다.",
     """포털 헤더가 없을 때만 임시 사용자로 동작하게 해 주세요.

```python
import os
from fastapi import Request, HTTPException

DEV_MODE = os.getenv("DEV_MODE", "false").lower() in ("1", "true", "yes")

def current_user(request: Request):
    uid = request.headers.get("X-User-Id")
    if not uid:
        if DEV_MODE:
            return {{"id": "hong", "name": "홍길동", "dept": "인사총무팀", "role": "admin"}}
        raise HTTPException(401, "포털을 통해 접속해 주세요.")
    return {{"id": uid,
            "name": request.headers.get("X-User-Name", ""),
            "dept": request.headers.get("X-User-Dept", ""),
            "role": request.headers.get("X-User-Role", "user")}}
```"""),

    ("포털 헤더를 읽는 곳이 안 보입니다",
     "포털이 붙여 주는 사용자 정보 읽기",
     "누가 쓰는지 알아야 하는 앱이면 로그인을 직접 만들지 않고 이 헤더를 읽습니다.",
     """`X-User-Id` · `X-User-Name` · `X-User-Dept` · `X-User-Role` 네 가지를
읽어서 쓰세요. 바로 위 DEV_MODE 예시에 같이 들어 있습니다."""),

    ("화면에 로그인·회원가입처럼 보이는 것이 있습니다",
     "로그인 화면 없애기",
     "로그인은 포털이 이미 했습니다. 앱이 또 물으면 직원이 두 번 로그인하게 됩니다.",
     """로그인·회원가입·비밀번호 찾기 화면과 그 코드를 지우고, 대신 포털이
붙여 주는 헤더를 읽어서 쓰세요."""),

    ("viewer 가 남아 있습니다",
     "권한을 user 와 admin 둘로만",
     "회사 표준은 두 가지뿐입니다. viewer 는 포털이 모르는 값이라 아무 데도 안 걸립니다.",
     """코드에서 viewer 를 지우고 user 로 바꿔 주세요."""),

    ("api/health 가 없습니다",
     "살아 있는지 확인하는 주소 만들기",
     "서버가 이 주소를 30초마다 불러 앱이 살아 있는지 봅니다. "
     "없으면 죽어도 아무도 모릅니다.",
     """이 한 줄만 있으면 됩니다.

```python
@app.get("/api/health")
def health():
    return {{"status": "ok"}}
```"""),

    ("expose 가 없습니다",
     "expose 넣기",
     "컨테이너 안에서 몇 번 포트를 쓰는지 알려 주는 줄입니다.",
     """docker-compose.yml 에 넣어 주세요. 컨테이너 안은 8080 으로 고정입니다.

```yaml
    expose: ["8080"]
```"""),

    ("./data 가 붙어 있지 않습니다",
     "data 폴더 붙이기",
     "저장하는 앱인데 이게 없으면 컨테이너를 다시 만들 때 내용이 전부 사라집니다.",
     """docker-compose.yml 에 넣어 주세요.

```yaml
    volumes:
      - ./data:/data
```"""),

    ("포털 이력 전송이 없습니다",
     "포털 이력으로 보내기",
     "누가 언제 무엇을 했는지 포털 한 곳에 모읍니다.",
     """중요한 동작이 끝날 때 포털에 한 줄 보내 주세요.

```python
async with httpx.AsyncClient(timeout=5) as c:
    await c.post(f"{{PORTAL}}/api/audit",
                 json={{"service": "{sid}", "user": user["id"], "action": "무엇을 했는지"}},
                 headers={{"X-Service-Token": os.getenv("AUDIT_TOKEN", "")}})
```"""),

    ("버전이 안 붙은 것이 있습니다",
     "라이브러리 버전 고정하기",
     "버전을 안 적으면 다음에 설치할 때 다른 버전이 들어와서, 어제 되던 것이 오늘 안 됩니다.",
     """requirements.txt 에 == 로 버전을 붙여 주세요.

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
```"""),

    ("설명이 거의 없습니다",
     "README 채우기",
     "다음에 맡을 사람이 무엇을 하는 앱인지 알 수 있어야 합니다.",
     """README.md 에 네 가지만 적어 주세요.

1. 이 앱이 무엇을 하는가
2. 누가 쓰는가
3. 무엇을 저장하는가 (개인정보가 있으면 반드시 적습니다)
4. 담당자가 누구인가"""),

    ("가 없습니다",          # `$f 가 없습니다` — 제출물 누락 (맨 뒤에 둔다)
     "빠진 파일 채우기",
     "사내 앱은 이 파일들이 다 있어야 합니다.",
     """지적된 파일을 만들어 넣어 주세요. 보통 빠지는 것은
`.env.example` · `.gitignore` · `README.md` 입니다."""),
]

MARK = re.compile(r"^\s*([✗△])\s+(.+?)\s*$")


# 앞의 것을 고치면 뒤의 것은 저절로 풀리는 관계.
# 파일이 통째로 없을 때 "그 파일 안의 이 줄이 없다" 를 따로 또 적으면,
# 받는 사람은 같은 파일 얘기를 네 번 읽게 된다.
SUPERSEDES: dict[str, set[str]] = {
    "docker-compose.yml 만들기": {
        "portal-net 에 붙이기",
        "portal-net 을 external 로 선언하기",
        "container_name 정하기",
        "바깥 포트 없애기",
        "expose 넣기",
        "data 폴더 붙이기",
    },
    "Dockerfile 만들기": {
        "베이스 이미지 버전 고정하기",
        "베이스 이미지를 회사 표준으로",
    },
}


def _fill(text: str, service_id: str, title: str) -> str:
    """빈칸만 채운다.

    str.format 을 쓰지 않는 이유 — 고치는 법에 코드 예시가 들어 있는데,
    거기 중괄호가 잔뜩 있다. format 은 그것까지 변수로 읽어 버린다.
    그래서 채울 이름만 직접 바꾸고, 예시 안에서 두 겹으로 적어 둔 중괄호는
    한 겹으로 되돌린다.
    """
    text = text.replace("{sid}", service_id).replace("{title}", title or service_id)
    return text.replace("{{", "{").replace("}}", "}")


def _match(msg: str) -> tuple[str, str, str] | None:
    for needle, title, why, how in RULES:
        if needle in msg:
            return title, why, how
    return None


def build(*, report: str, service_id: str, title: str, verdict: str) -> str:
    """검사 결과에서 붙여넣을 프롬프트 한 덩어리를 만든다."""
    musts: list[tuple[str, str, str, str]] = []   # ✗
    betters: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()

    for line in report.splitlines():
        m = MARK.match(line)
        if not m:
            continue
        mark, msg = m.group(1), m.group(2)
        hit = _match(msg)
        if not hit:
            continue
        head, why, how = hit
        if head in seen:
            continue
        seen.add(head)
        (musts if mark == "✗" else betters).append(
            (head, why, _fill(how, service_id, title), msg))

    # 큰 것 하나로 덮이는 항목은 뺀다
    covered: set[str] = set()
    for head, _, _, _ in musts + betters:
        covered |= SUPERSEDES.get(head, set())
    if covered:
        musts = [x for x in musts if x[0] not in covered]
        betters = [x for x in betters if x[0] not in covered]

    out: list[str] = []
    out.append("사내 포털에 올리려고 만든 앱이 입고 검사에서 걸렸습니다.")
    out.append("아래를 고쳐서 **프로젝트 전체를 다시 만들어** 주세요. "
               "고친 파일만이 아니라 zip 으로 묶을 수 있게 전부 주세요.")
    out.append("")
    out.append(f"- 서비스 ID : {service_id}")
    out.append(f"- 앱 이름   : {title or service_id}")
    out.append("")

    if musts:
        out.append("## 반드시 고쳐야 하는 것")
        out.append("")
        for i, (head, why, how, msg) in enumerate(musts, 1):
            out.append(f"### {i}. {head}")
            out.append("")
            out.append(f"검사에서 나온 말 — {msg}")
            out.append("")
            out.append(why)
            out.append("")
            out.append(how)
            out.append("")

    if betters:
        out.append("## 고치면 더 좋은 것")
        out.append("")
        for i, (head, why, how, msg) in enumerate(betters, 1):
            out.append(f"### {i}. {head}")
            out.append("")
            out.append(f"검사에서 나온 말 — {msg}")
            out.append("")
            out.append(why)
            out.append("")
            out.append(how)
            out.append("")

    out.append("## 고치면서 지킬 것")
    out.append("")
    out.append("- 컨테이너 안 포트는 **8080 고정**, 바깥 포트(`ports:`)는 열지 않습니다.")
    out.append("- 로그인을 만들지 않습니다. 포털이 붙여 주는 "
               "`X-User-Id` · `X-User-Name` · `X-User-Dept` · `X-User-Role` 을 읽습니다.")
    out.append("- 권한은 `user` 와 `admin` 둘뿐입니다.")
    out.append("- 비밀번호·토큰을 코드에 적지 않습니다. `.env.example` 에는 이름만 적습니다.")
    out.append("- 베이스 이미지와 라이브러리는 **버전을 붙여 고정**합니다.")
    out.append("- 화면에서 API 를 부를 때 주소 앞에 슬래시를 붙이지 않습니다.")
    out.append("- 바깥 인터넷 주소(CDN·폰트)를 부르지 않습니다.")
    out.append("")
    out.append("다 고치셨으면 압축해서 포털의 「사내앱 입고」에 다시 올려 주세요.")
    return "\n".join(out)
