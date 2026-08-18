# 코드 리뷰 — IT Asset Portal

실제로 서버를 띄우고 API를 호출해가며 확인한 결과다.
DB는 SQLite로 붙여서 돌렸다(뒤에 이유 설명).

---

## 결론 먼저

**미흡하지 않다.** 구조·인증·마이그레이션·프론트까지 갖춘 실동작 프로젝트고,
무엇보다 "퇴사 처리하면 자산 회수 + IP 해제"처럼 **업무를 아는 사람만 만들 수 있는 기능**이 들어있다.
포트폴리오로 충분히 내세울 수 있다.

다만 **배포를 막는 문제 2개**와 **보안 문제 2개**가 있었다. 아래에 정리하고 전부 고쳐뒀다.

---

## 잘 되어 있는 것

| 항목 | 평가 |
|---|---|
| 레이어 분리 | `models` / `schemas` / `api` / `core` / `db` 로 명확히 나뉘어 있다 |
| Alembic 마이그레이션 | 9개 리비전. 스키마 변경 이력이 남는다 |
| 인증 | bcrypt 해싱 + JWT + `require_admin` 역할 가드. 교과서적으로 맞다 |
| 퇴사 처리 자동화 | 자산 회수 + IP 해제 + 상태 변경을 한 번에. **이 프로젝트의 백미** |
| 만료 알림 | 라이선스 30일 / 렌탈 60일 임박 조회 |
| IP 사용률 | 등록된 대역의 실제 주소 수로 계산 (주석에 "예전엔 512 고정" 기록까지 남아있음) |
| 프론트 | 7개 화면 SPA. 직원별 현황은 검색·정렬·페이징·펼침까지 |
| `.gitignore` | 사내 실데이터(`data/`)와 `.env`를 제외. **위생이 좋다** (추적 파일 60개뿐) |

동작 확인한 흐름:

```
로그인 → 직원 등록 → 자산 등록 → 지급 → 재지급(기존 자동 반납)
      → IP 할당 → 퇴사 처리(자산 2대 회수 + IP 1개 해제) → 대시보드 반영
```

전부 정상이었다. 회귀 테스트 **14/14 통과**.

---

## 고친 것

### 1. 자산 지급 API가 항상 500으로 죽음 (치명)

`app/api/asset_assignments.py:53`

```python
db.query(AssetAssignment).filter(
    AssetAssignment.asset_id == asset_id,   # ← 이런 변수가 없다
```

`POST /asset-assignments/` 를 부르면 `NameError` 로 100% 실패했다.
의도는 "새로 지급하기 전에 기존 지급을 반납 처리"인데 변수명이 틀렸다.

```python
    AssetAssignment.asset_id == assignment_data.asset_id,   # 수정
```

> `POST /assets/{id}/assign` 라는 다른 경로가 따로 있어서 그동안 안 드러난 것으로 보인다.
> 같은 종류(정의되지 않은 이름)의 버그가 더 있는지 pyflakes로 전수 검사했고, **이것 하나뿐**이었다.

### 2. `requirements.txt` 가 UTF-16 (배포 블로커)

Windows PowerShell 에서 `pip freeze >` 로 만들면 UTF-16 으로 저장된다.
리눅스 서버에서 `pip install -r requirements.txt` 가 그대로 실패한다.
→ UTF-8(LF)로 변환했다.

### 3. CORS 가 전면 개방 (보안)

```python
allow_origins=["*"], allow_credentials=True
```

이 둘은 같이 쓸 수 없는 조합이다. 브라우저 표준상 거부되고,
무엇보다 **아무 웹사이트나 로그인한 사용자 권한으로 이 API를 호출**할 수 있게 된다.
→ `.env` 의 `CORS_ORIGINS` 에 명시한 출처만 허용하도록 변경.

### 4. `SECRET_KEY` 기본값이 `"change-me"` (보안)

`.env` 를 안 넣고 띄우면 **조용히** 공개된 키로 토큰을 서명한다.
누구나 관리자 토큰을 위조할 수 있다.
→ `PRODUCTION=true` 인데 기본 시크릿이면 **기동 자체를 중단**하도록 변경.

### 5. 자산 유형/상태에 검증이 없었음

`asset_type`, `status` 가 DB에서도 스키마에서도 그냥 문자열이라
API로 `"컴퓨터"` 든 `"PC"` 든 아무 값이나 들어갔다.
실제로 확인해보니 프론트 라벨표에는 `LAPTOP/DESKTOP/...` 만 있어서,
그 밖의 값이 들어오면 화면에 **영문 원문이 그대로 노출**되고 집계도 따로 잡혔다.

→ `app/core/enums.py` 에 값을 모으고 Pydantic 이 검증하게 했다.
   프론트 `ASSET_TYPES` 에 빠져 있던 `NETWORK` 도 추가.

한 가지 주의해서 처리한 부분: **응답 스키마는 일부러 `str` 로 남겼다.**
이미 DB에 들어가 있는 예전 값까지 Enum 으로 검증하면
규격 밖 값 하나 때문에 **목록 조회 전체가 500** 으로 죽는다.
쓰기는 엄격하게, 읽기는 관대하게.

### 6. `docker-compose.yml` 정리

- `version: "3.9"` → 최신 Compose 에서 무시되고 경고만 남기므로 제거
- DB 비밀번호 하드코딩 → `.env` 에서 읽도록, 없으면 기동 실패
- `5432:5432` → `127.0.0.1:5432:5432` (외부에 DB 포트를 열지 않는다)
- `postgres:17` → `17-alpine`, healthcheck 추가

### 7. `/healthz` 추가

컨테이너 헬스체크용. 인증 없이 접근 가능하다.

---

## 아직 남은 것 (급하지 않음)

- 미사용 import 10개 (`pyflakes` 로 확인, 동작에는 영향 없음)
- `POST /assets/{id}/assign` 과 `POST /asset-assignments/` 가 기능이 겹친다. 하나로 정리하면 좋다
- 테스트 코드가 없다. 이번에 쓴 회귀 시나리오를 `pytest` 로 옮겨두면 포트폴리오 가치가 올라간다
- `/rental-contracts` 는 끝 슬래시가 없으면 307 리다이렉트가 난다. 리버스 프록시 뒤에서 문제될 수 있다

---

## 서버 사양 관련 (중요)

현재 `DATABASE_URL` 기본값이 PostgreSQL 이고 `docker-compose` 도 Postgres 를 띄운다.
그런데 배포 대상 서버는 **Azure B2ts v2 — 2 vCPU / RAM 1GiB** 다.

| 구성 | 예상 사용 | 남는 여유 |
|---|---|---|
| Ubuntu + Docker + nginx + FastAPI + **SQLite** | 465 MB | **559 MB** |
| Ubuntu + Docker + nginx + FastAPI + **PostgreSQL** | 705 MB | 319 MB |

**이번 리뷰의 모든 테스트를 SQLite 로 돌렸고, 코드 수정 없이 전부 통과했다.**
SQLAlchemy 를 쓰고 있어서 접속 문자열만 바꾸면 된다.

```bash
# .env
DATABASE_URL=sqlite+pysqlite:///./data/app.db
```

주의: SQLite 를 쓸 때는 WAL 모드를 켜야 쓰기 중에도 읽기가 막히지 않는다.
그리고 Alembic 마이그레이션은 SQLite 에서 `ALTER COLUMN` 제약이 있으므로,
초기 구축은 마이그레이션으로, 이후 컬럼 변경은 batch 모드로 처리해야 한다.

사용자가 늘거나 서버를 키우면 그때 PostgreSQL 로 돌아가면 된다. 코드는 그대로다.

---

## 포트폴리오 관점

기술 스택보다 **이 대목들이 설득력이 있다.**

1. **퇴사 처리 한 번에 자산 회수 + IP 해제** — 연간 체크리스트의 "퇴사자 계정 비활성화"를 자동화한 것
2. **만료 임박 대시보드** — "계약 만료를 지나서야 알게 되는" 문제를 직접 푼 것
3. **엑셀 임포트 스크립트** — 기존 PC 대장을 그대로 옮겨온 현실적인 마이그레이션 경로
4. **SQLite 선택** — 남들이 쓰니까가 아니라 서버 제약(1GiB)과 부하(동시 한 자릿수)를 재고 고른 것

면접에서 물어보기 좋은 지점이라, 위 4개는 답변을 미리 준비해두면 좋다.
