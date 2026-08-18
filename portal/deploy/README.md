# 서버 배치

이 폴더는 **포털 레포가 아니라 서버(또는 별도 `proxy` 레포)에 두는 파일들**이다.
포털을 처음 배포할 때 서버로 복사해 쓴다.

---

## 1. 폴더 구조

기존 서버 방식과 같다. 서비스마다 폴더를 나란히 둔다.

```
/srv/portal/
├── portal/          ← 챗 포털 (메인). 이 레포
│   ├── app/  static/  Dockerfile  docker-compose.yml
│   ├── .env         ← 서버에만 있는 파일. git 에 올리지 않는다
│   └── data/        ← SQLite 3개. 백업 대상
├── ai-report/       ← 별도 레포
│   ├── main.py  index.html  Dockerfile  docker-compose.yml
│   └── data/        ← 엑셀. 백업 대상
├── assets/          ← 앞으로 만들 것들도 같은 방식
├── manual/
└── proxy/           ← nginx. 이 폴더의 내용
    ├── docker-compose.yml
    └── conf.d/portal.conf
```

**왜 한 폴더 안에 넣지 않는가.** 팀에서 각자 레포를 만들어 커밋하고
검토 후 배포하는 방식이라, 서비스 하나가 곧 레포 하나다.
포털 안에 ai-report 를 넣으면 두 사람이 같은 레포를 건드리게 되고,
포털만 고쳐도 ai-report 가 같이 재배포된다.

**왜 compose 를 하나로 합치지 않는가.** 같은 이유다. 하나로 합치면
`docker compose up -d --build` 한 번에 전부 재시작된다. 서비스가 네 개를
넘어가면 "매뉴얼 오타 하나 고쳤는데 챗이 끊겼다"가 생긴다.

대신 **같은 도커 네트워크**에 붙여 서로 컨테이너 이름으로 부르게 한다.

---

## 2. 처음 한 번

```bash
# 서비스들이 서로를 찾을 공용 네트워크
docker network create demo-net
```

각 서비스의 `docker-compose.yml` 맨 아래에 이게 들어 있으면 된다.

```yaml
networks:
  demo-net:
    external: true
```

---

## 3. 주소 정리

nginx 하나가 앞에 서고, 뒤로 각 서비스에 넘긴다.
직원은 포트 번호를 외울 필요가 없고, 앞으로 앱이 늘어도 주소 체계가 유지된다.

| 주소 | 가는 곳 |
|---|---|
| `/` | portal:8080 (챗 화면) |
| `/ai-report/` | aireport:8080 |
| `/assets/` | assets:8080 |

관리자 화면에서 서비스를 등록할 때 **경로(URL)** 칸에 `/ai-report/` 처럼
넣으면 이 주소 체계와 그대로 맞는다.

---

## 4. 배포

각 서비스 폴더에서 따로 돈다.

```bash
cd /srv/portal/portal
git pull
docker compose up -d --build
```

`deploy.sh` 를 쓰면 한 줄이다.

```bash
./deploy.sh portal
./deploy.sh ai-report
./deploy.sh              # 전부
```

---

## 5. 서비스 사이 인증

ai-report 같은 옆 서비스도 "이 사람이 누구인지"를 알아야 한다.
포털이 판정하고 옆 서비스는 물어보기만 한다. 판정 기준이 두 벌이 되면
"포털에선 되는데 리포트에선 안 된다"가 생긴다.

```
직원 브라우저
   │  로그인 → 포털이 portal_token 쿠키를 심는다 (HttpOnly, 도메인 전체)
   │
   ├─→ /            포털이 직접 처리
   │
   └─→ /ai-report/  ai-report 컨테이너
                      │  쿠키를 그대로 들고
                      └─→ http://demo-portal:8080/api/me  ← 포털이 판정
```

ai-report 의 `docker-compose.yml` 에서 이 값만 바꾸면 된다.

```yaml
environment:
  # 같은 네트워크이므로 IP 대신 컨테이너 이름으로 부른다.
  # IP 를 박아두면 서버를 옮길 때마다 전부 고쳐야 한다.
  - PORTAL_API_URL=http://demo-portal:8080
  # 포털 .env 의 AUDIT_TOKEN 과 같은 값
  - AUDIT_TOKEN=...
```

포털은 옆 서비스를 위해 세 가지를 제공한다.

| 엔드포인트 | 용도 |
|---|---|
| `GET /api/me` | 쿠키로 누구인지 확인. `logged_in`, `is_admin`, `id`, `dept` 포함 |
| `GET /api/verify?service=ai-report` | 이 사람이 그 서비스를 쓸 수 있는지 |
| `POST /api/audit` | 옆 서비스의 동작을 포털 이력에 남긴다 (`X-Audit-Token` 필요) |

`/api/verify` 를 쓰면 접근 범위를 관리자 화면에서 바꾸는 것만으로
옆 서비스의 접근도 같이 바뀐다. 서비스마다 명단을 또 관리하지 않아도 된다.

---

## 6. HTTPS

지금은 사내망이라 http 로 두고, 도메인이 붙으면 `portal.conf` 의
주석 처리된 443 블록을 살린다. certbot 인증서는 `proxy/certs` 에 둔다.

HTTPS 로 가면 포털 `.env` 에 `COOKIE_SECURE=1` 을 넣는다.
그래야 쿠키가 암호화된 연결로만 오간다.

---

## 7. 백업

두 폴더만 챙기면 된다.

```bash
tar czf portal-$(date +%F).tar.gz \
    /srv/portal/portal/data \
    /srv/portal/ai-report/data
```

`portal/data` 안의 `users.db` 가 없어지면 **계정이 전부 사라진다.**
컨테이너를 지웠다 다시 만드는 것과는 다른 문제이므로, 이 폴더는
정기적으로 다른 디스크에 복사해 둘 것.
