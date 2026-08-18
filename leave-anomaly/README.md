# 휴가 이상감지 (leave-anomaly)

> 회사 표준 규칙 **v2 · 2026-08-07** 기준으로 만들었습니다.

| 항목 | 내용 |
| --- | --- |
| 프로그램 이름 | 휴가 이상감지 |
| 서비스 ID | `leave-anomaly` |
| 접속 주소 | `/leave-anomaly/` (사내 포털 아래) |
| 담당자 | 인사총무팀 (요청: 신윤성) |
| 만든 날짜 | 2026-08-10 |
| 컨테이너 포트 | 8080 (바깥 포트 없음 — 앞단 nginx 가 경로로 넘겨줌) |
| 데이터 저장 위치 | `/data/app.db` (SQLite), 업로드 원본은 `/data/uploads` |
| 원본 | Team Planner `oz` 부서 앱 「휴가 이상감지」 (브라우저 단독 실행판)을 사내 서버용으로 옮긴 것 |

---

## 1. 무엇을 하는 프로그램인가

인사총무팀이 웍스에서 내려받은 **연차 사용내역**·**연차 발생내역** 엑셀을 올리면,
아래 세 가지를 자동으로 찾아 표로 보여줍니다.

1. **이상 패턴** — 최근 21일 안에서 *고립된 평일 연차*(앞뒤가 휴일·다른 연차와 이어지지 않는 연차)가
   반복되는 사람을 **위험 / 검토 / 관찰** 로 분류합니다.
2. **저사용** — 연중 경과율보다 개인 사용률이 25%p 이상 낮은(연차를 쌓아두는) 사람.
3. **급증** — 최근 60일 사용량이 직전 기대치의 2.5배 이상인(안 쓰다 몰아 쓰는) 사람.

기존에는 담당자가 엑셀을 직접 정렬·필터링해 눈으로 찾아야 했고, 사람마다 기준이 달라
같은 자료로도 결과가 달라졌습니다. 이 앱은 기준을 코드 한 곳(`app/config.py`)에 고정해
누가 돌려도 같은 결과가 나오게 합니다.

### 감지 기준 요약

- 대상: 휴가그룹이 **연차휴가**인 기록만. 사람 식별은 **사원번호** 기준.
- 같은 날 여러 건은 **합산**합니다(오전 반차 + 오후 반차 = 연차 1.0).
- 차감일수: 연차 1 · 반차 0.5 · 반반차 0.25 · 반반반차 0.125. 오전/오후는 시작 시간으로 판정.
- 가중치는 **휴가 유형 × 요일(월~금)** 로 부여합니다. (화면의 「감지 기준 자세히 보기」에 표로 나옵니다)
- **주말은 없는 날로 취급**합니다 → 금요일 + 월요일 연차는 "이어진 것"으로 보고 고립에서 제외.
- 전 직원의 50% 이상이 쉬는 날(집단연차)은 고립 판정에서 제외.
- 등급: 위험 = 점수 3.0↑ **그리고** 고립 3회↑ / 검토 = 점수 2.5↑ **또는** 고립 3회↑ / 관찰 = 점수 2.0↑.

모든 임계값은 `app/config.py` 의 `ANOMALY_CONFIG` 한 곳에 있습니다. 기준을 바꾸려면 이 파일만 고치면 됩니다.

---

## 2. 로그인과 권한

로그인 화면·회원가입은 **없습니다.** 사내 포털이 앞단에서 처리하고 아래 헤더를 붙여 넘겨줍니다.

| 헤더 | 내용 |
| --- | --- |
| `X-User-Id` | 사번 또는 아이디 |
| `X-User-Name` | 이름 (퍼센트 인코딩 → 서버에서 `unquote`) |
| `X-User-Dept` | 부서 (퍼센트 인코딩 → 서버에서 `unquote`) |
| `X-User-Role` | `admin` 또는 `user` |

헤더가 없을 때는 `DEV_MODE=true` 인 경우에만 테스트용 계정(`hong` / 홍길동 / 인사총무팀)으로 동작하고,
`DEV_MODE` 가 false 인데 헤더가 없으면 **401** 로 거절합니다.

### ⚠️ 표준과 다르게 정한 부분 (담당자 확인 필요)

이 앱은 **접근 정책을 앞단(포털/로그인)에서 정하고, 앱 안에서는 권한을 나누지 않습니다.**
즉 **접속이 확인된 사람은 누구나 조회·업로드·삭제를 모두 할 수 있습니다.**
표준 기본값("삭제는 admin")과 다른 부분은 **삭제도 user 가 할 수 있다는 점** 하나입니다.

- `X-User-Role` 헤더는 그대로 읽어서 `api/me` 로 보여주기만 하고, 접근 제한에는 쓰지 않습니다.
- 나중에 삭제만 담당자로 제한하고 싶으면, `app/main.py` 의 `remove_dataset`·`remove_holiday` 에서
  `Depends(require_user)` 를 `Depends(require_admin)` 으로 바꾸기만 하면 됩니다.
  (`require_admin` 은 `app/auth.py` 에 그대로 남겨 두었습니다.)

---

## 3. API 목록

| 메서드 | 주소 | 하는 일 | 필요 권한 |
| --- | --- | --- | --- |
| GET | `api/health` | 앱이 정상으로 켜졌는지 확인 | 없음 |
| GET | `api/me` | 접속자의 이름·부서·권한 | user |
| GET | `api/criteria` | 감지 기준(가중치표·등급 임계값) 전체 | user |
| GET | `api/holidays` | 고립 판정에 쓰는 휴일 목록(법정 + 회사) | user |
| POST | `api/holidays` | 회사 자체 휴일 등록 | user |
| DELETE | `api/holidays/{date}` | 회사 자체 휴일 삭제 | user |
| GET | `api/datasets` | 현재 올라와 있는 파일명·건수·업로드 시각 | user |
| POST | `api/datasets/{kind}` | 사용내역(`usage`)·발생내역(`accrual`) 엑셀 업로드 | user |
| DELETE | `api/datasets/{kind}` | 올린 데이터 삭제 | user |
| GET | `api/analysis?ref=YYYY-MM-DD` | 이상 패턴·저사용·급증 결과 전체 | user |
| GET | `api/audit?limit=100` | 이 앱에서 누가 무엇을 했는지 최근 기록 | user |

> 모든 API 가 `user` 입니다 — 접근 정책은 앞단(포털/로그인)에서 정한다는 전제입니다.
> 누가 무엇을 했는지는 `audit_log` 와 포털 이력에 그대로 남습니다.

> 화면에서 API 를 부를 때는 항상 상대경로(`fetch("api/health")`)를 씁니다.
> 서버 라우트만 슬래시로 시작합니다(`@app.get("/api/health")`).

## 4. 데이터 구조 (SQLite · `/data/app.db`)

| 표 | 내용 |
| --- | --- |
| `dataset` | 사용내역/발생내역 최신본 1건씩. 파일명·건수·정규화된 행(JSON)·업로더·업로드 시각 |
| `company_holiday` | 회사 자체 휴일(창립기념일 등). 날짜(PK)·이름 |
| `audit_log` | 업로드·삭제 등 앱 자체 이력 |

업로드 원본 파일은 `/data/uploads` 아래에만 저장합니다.
허용 확장자는 `.xlsx` / `.csv`, 최대 20MB이며, 확장자뿐 아니라 **PK 시그니처·실제 열림 여부·필수 열 존재**까지
확인해 잘못된 파일을 거절합니다.

## 5. 포털 연동

- 앱이 뜰 때 `POST {PORTAL_API_URL}/api/services/register` 로 자기 자신을 등록합니다(실패해도 앱은 정상 동작).
- 업로드·삭제는 `POST {PORTAL_API_URL}/api/audit` 로 포털 이력에 보냅니다(실패해도 무시, 앱 자체 기록은 남음).
- 검색 키워드: `휴가 이상감지, 연차 이상, 연차 남용, 휴가 패턴, 고립 연차, 금요일 연차, 연차 저사용, 연차 급증, 휴가 분석` 등.

## 6. 환경변수

`.env.example` 을 `.env` 로 복사해 채웁니다.

| 이름 | 설명 |
| --- | --- |
| `DEV_MODE` | `true` 면 포털 헤더 없이 테스트 계정으로 동작 (운영에서는 비워 둘 것) |
| `PORTAL_API_URL` | 사내 포털 API 주소 |
| `AUDIT_TOKEN` | 포털 서비스 등록·이력 전송용 토큰 |

## 7. 실행 방법 (서버)

```bash
cp .env.example .env      # 값 채우기
docker network create demo-net   # 이미 있으면 생략
docker compose up -d --build
docker compose logs -f leave-anomaly
```

앞단 nginx 에서 `/leave-anomaly/` 를 이 컨테이너의 8080 으로 넘겨주면 됩니다.

## 8. 테스트 방법

```bash
# 컨테이너 안에서
curl -s localhost:8080/api/health          # {"ok":true,...}
# 포털 헤더 흉내내기
curl -s -H "X-User-Id: hong" -H "X-User-Role: user" localhost:8080/api/me
curl -s -H "X-User-Id: hong" -H "X-User-Role: user" localhost:8080/api/analysis   # user 로도 열려야 정상
```

- `DEV_MODE=true` 로 두고 브라우저에서 열면 로그인 없이 화면을 확인할 수 있습니다.
- 권한 구분이 없으므로 `X-User-Role` 을 `user` 로 보내도 모든 기능이 동작해야 정상입니다.
- 사용내역 엑셀만 올리면 「이상 패턴」·「급증」이, 발생내역까지 올리면 「저사용」이 함께 계산됩니다.
- 기준일을 바꾸면 저사용·급증 계산 시점이 달라집니다.

## 9. 내 PC 에서 실행하는 방법 (5줄)

```
1) 압축을 풀고 폴더로 이동
2) python -m venv .venv  &&  .venv\Scripts\activate   (Mac/Linux: source .venv/bin/activate)
3) pip install -r requirements.txt
4) set DEV_MODE=true  &&  set DATA_DIR=.\data         (Mac/Linux: export DEV_MODE=true DATA_DIR=./data)
5) uvicorn app.main:app --port 8080  →  브라우저에서 http://localhost:8080/
```

## 10. 제출물 점검

| 표준 요구 | 실제 파일 |
| --- | --- |
| 소스코드 | `app/main.py`, `app/analyzer.py`, `app/parsers.py`, `app/db.py`, `app/auth.py`, `app/portal.py`, `app/config.py`, `app/holidays.py`, `app/static/*` |
| requirements.txt | ✅ |
| Dockerfile | ✅ (python:3.13-slim, 8080, ports 없음) |
| docker-compose.yml | ✅ (expose only, demo-net external, ./data:/data) |
| .env.example | ✅ (DEV_MODE / PORTAL_API_URL / AUDIT_TOKEN) |
| .gitignore | ✅ (.env, data/) |
| README.md | ✅ (이 파일) |

빠진 파일 없음.
