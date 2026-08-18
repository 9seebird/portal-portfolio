# IT 안내 (it-guide)

> 회사 표준 규칙 **v2** 기준. 다만 이 앱은 **백엔드가 없습니다** —
> nginx 하나가 정적 파일을 주는 것이 전부라, 규칙 중 서버 쪽 항목은 해당이 없습니다.

- **이름·용도** : 매뉴얼 · 운영 체크리스트 · ITO 비용처리 · 프롬프트 생성기
- **담당** : 인사총무팀 IT 담당
- **만든 날** : 2026-08-07 (옛 포털 `it-portal/portal-web` 에서 옮겨 옴)
- **컨테이너 안 포트** : 80 (바깥 포트는 열지 않습니다)

## 컨테이너는 하나인데 서비스는 넷입니다

포털의 권한은 **서비스 단위**로 걸립니다. 매뉴얼은 전 직원이 봐도 되지만
운영 체크리스트는 담당자만 봐야 할 수 있습니다. 그래서 프록시에서 경로를
넷으로 나누고 각각 따로 권한을 묻습니다 (`proxy/apps/*.conf`).
정적 파일 넷 때문에 컨테이너를 넷 띄울 이유는 없습니다.

| 서비스 ID | 이름 | 주소 |
|---|---|---|
| `manual` | IT 매뉴얼 | `/manual/` |
| `checklist` | IT 운영 체크리스트 | `/checklist/` |
| `ito-cost` | ITO 비용처리 | `/ito-cost/` |
| `prompt` | 바이브코딩 프롬프트 생성기 | `/prompt/` |

## 실행

```powershell
.\deploy.ps1 it-guide proxy portal
```

## 데이터 저장 위치

**DB 가 없습니다.** 내용이 파일 안에 그대로 들어 있습니다.

| 무엇 | 어디 |
|---|---|
| 매뉴얼 글 | `web/manuals/data/manuals.js` |
| 매뉴얼 그림 | `web/manuals/images/<매뉴얼id>/` |
| 체크리스트 | `web/checklist/index.html` |
| 프롬프트 규칙 | `web/prompt/index.html` 의 `RULES` 배열 |

볼륨으로 붙여 두어서 **덮어쓰고 새로고침만 하면 반영됩니다.**
도커 이미지를 다시 만들 필요가 없습니다. 고치는 방법은 `붙이는법.md` 4장에 있습니다.

## 환경변수

| 이름 | 뜻 |
|---|---|
| `AUDIT_TOKEN` | 포털과 나눠 갖는 토큰. 등록 컨테이너가 씁니다 |

`DEV_MODE` · `PORTAL_API_URL` 은 백엔드가 없어 쓰지 않습니다.

## API 목록

정적 파일 앱이라 **API 가 없습니다.** 권한은 앞단 프록시가 포털에 물어봐서
막습니다(`auth_request`). 앱까지 요청이 오면 그건 이미 통과한 사람입니다.

| 주소 | 하는 일 | 권한 |
|---|---|---|
| `GET /healthz` | 켜졌는지 확인 | 없음 |
| `GET /manual/` 외 | 화면 파일 | 각 서비스의 접근 범위 |

## 포털 등록

앱이 스스로 등록할 코드가 없어서, **한 번 뛰고 끝나는 작은 컨테이너**
(`guide-register`)가 대신 넷을 등록합니다. 확인은 `docker logs guide-register`.

## 테스트

```bash
curl -s localhost/manual/ | head -3          # 화면이 오는지
docker exec guide-web wget -qO- localhost/healthz   # ok
docker logs guide-register                   # 등록 결과
```
