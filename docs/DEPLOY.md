# 서버에 올리기 (우분투)

Azure · AWS · 어디든 우분투 24.04 기준입니다. 도커만 있으면 됩니다.

처음 한 번은 20분쯤 걸립니다. 그 뒤로는 `git pull && ./deploy.sh` 한 줄입니다.

---

## 1. 서버 만들기

작아도 됩니다. 다만 메모리가 2GB 미만이면 엑셀을 다루는 앱이 위험합니다.

| | 최소 | 넉넉하게 |
|---|---|---|
| CPU | 1 | 2 |
| 메모리 | 2GB | 4GB |
| 디스크 | 20GB | 40GB |

Azure 라면 `Standard_B1ms`(1core/2GB) 로 시작해서 모자라면 `B2s` 로 올리면 됩니다.

### 메모리가 1GB 뿐이라면

돌아갑니다. 다만 **두 가지를 해야** 합니다.

가만히 있을 때 앱들이 얼마나 먹는지 실측한 값입니다.

```
portal 47  ai-report 66  biz-plan 56  asset-api 62  asset-web 15
leave-anomaly 44  manual-import 46  guide-web 11  proxy 11
                                                     ─────────────
                                                        합계 358MB
```

우분투와 도커 데몬이 250~300MB 를 쓰므로, 1GB 에서 남는 것은 400~450MB 입니다.
엑셀 하나를 올려 계산하는 순간이 위험합니다.

**스왑을 2GB 만듭니다** — 없으면 순간적으로 몰릴 때 커널이 컨테이너를
그냥 죽입니다(OOM). 로그에도 이유가 안 남아서 "갑자기 502" 로만 보입니다.

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h                      # Swap 줄에 2.0Gi 가 보이면 됩니다
```

스왑은 느립니다. 평소에 쓰라는 게 아니라 **드물게 몰릴 때 죽지 않게** 하는 것입니다.

**열어 둘 포트는 두 개뿐입니다** — 22(SSH) · 80(HTTP) · 443(HTTPS).
그 외에는 열지 않습니다. 앱들은 컨테이너 안에서만 이야기하므로 바깥에 열 이유가 없습니다.

> Azure 는 방화벽이 두 겹입니다 — **네트워크 보안 그룹(NSG)** 과 서버 안의 `ufw`.
> 한쪽만 열면 안 됩니다. 「방화벽을 열었는데 안 된다」의 대부분이 이것입니다.

---

## 2. 도커 설치

```bash
sudo apt update
sudo apt install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo tee /etc/apt/keyrings/docker.asc > /dev/null
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 매번 sudo 를 치지 않으려면
sudo usermod -aG docker $USER
newgrp docker            # 또는 로그아웃 후 다시 로그인

docker compose version   # 확인
```

우분투 기본 저장소의 `docker.io` 를 쓰지 않는 이유 — `docker compose`(플러그인) 가
따라오지 않아서 `docker-compose`(옛 파이썬 판)를 따로 깔아야 하고,
그 둘은 `include:` 같은 최신 문법에서 갈립니다.

---

## 3. 받아서 띄우기

```bash
sudo mkdir -p /srv && sudo chown $USER /srv
cd /srv
git clone <이 저장소> portal
cd portal
```

### AI 키 넣기 (챗을 보이려면)

```bash
cp portal/.env.example portal/.env
nano portal/.env
```

```
PROVIDER=openai
OPENAI_API_KEY=여기에-키
OPENAI_BASE_URL=https://api.openai.com/v1      # 게이트웨이를 쓰면 그 주소
MODEL=gpt-5-mini
```

키가 없어도 **챗을 뺀 나머지 앱은 전부 돌아갑니다.**
자산 · 사업계획 · 연차 · 리포트 · 매뉴얼은 AI 를 쓰지 않습니다.

### 띄우기

```bash
./demo.sh              # 80 포트로 바로  (혼자 보는 서버)
./demo.sh --behind     # 127.0.0.1:8081 로만 (앞에 nginx 를 둘 때)
```

> 내 PC(윈도우)에서 먼저 확인하실 때는 같은 자리에 `.\demo.ps1` 을 쓰시면 됩니다.
> 하는 일과 순서가 같습니다.

처음에는 이미지를 빌드하느라 5~10분 걸립니다. 두 번째부터는 1분입니다.

끝나면 이렇게 나옵니다.

```
  아이디  demo
  비밀번호 demo1234

  http://localhost/
```

---

## 4. 도메인과 HTTPS

도메인이 없어도 IP 로 볼 수는 있습니다. 다만 **로그인 쿠키 때문에라도 HTTPS 를 붙이는 편이 낫습니다.**

### 4-1. 앞에 nginx 세우기

```bash
sudo apt install -y nginx
./demo.sh --behind          # 컨테이너를 127.0.0.1:8081 로 내린다
```

`--behind` 가 중요합니다. 이걸 빼면 8081 이 인터넷 전체에 열려서
**인증서와 접근 로그를 건너뛰는 뒷문**이 생깁니다.

`/etc/nginx/sites-available/portal` :

```nginx
server {
    listen 80;
    server_name portal.example.com;

    # 업로드 파일 크기. 앱 쪽(UPLOAD_MAX_MB)보다 넉넉하게.
    # ★ 여기만 작으면 큰 파일이 413 으로 튕기는데, 화면에는 단서가 없습니다.
    client_max_body_size 150m;

    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        # 클라이언트가 넣은 값을 덮어씁니다. 안 그러면 접속 IP 를 위조할 수 있고
        # 체험판의 IP 당 챗 제한이 무의미해집니다.
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 챗 응답은 SSE 로 조금씩 내려옵니다. 버퍼링을 켜면 다 끝난 뒤
        # 한 번에 나와서 진행 표시가 무의미해집니다.
        proxy_buffering off;
        proxy_read_timeout 600s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/portal /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 4-2. 인증서

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d portal.example.com
```

**HTTPS 로 바꾼 뒤에 한 줄을 더 고쳐야 합니다.**

```bash
sed -i 's/^COOKIE_SECURE=.*/COOKIE_SECURE=1/' portal/.env
./deploy.sh portal
```

이걸 안 하면 쿠키에 `secure` 가 안 붙어서, 옆 앱으로 이동할 때 로그인이 풀립니다.
반대로 **http 인 채로 1 로 두면 쿠키가 아예 저장되지 않아 로그인 자체가 안 됩니다.**

---

## 5. 확인

```bash
docker ps                                    # 컨테이너가 다 떠 있나
curl -s localhost/health                     # {"ok":true}
python3 tools/check_demo.py https://portal.example.com

# 파이썬이 없으면 (도커 네트워크 안에서 프록시를 이름으로 부릅니다)
docker run --rm --network demo-net -v "$PWD/tools:/t" \
  python:3.12-slim python /t/check_demo.py http://demo-proxy
```

마지막 줄이 제일 중요합니다. 설정 파일을 읽는 게 아니라 **바깥에서 진짜로 요청을 보내**
막혀야 할 것이 막히는지 봅니다. 하나라도 「실패」가 뜨면 공개하지 마세요.

---

## 6. 평소 관리

### 다시 배포

```bash
cd /srv/portal
git pull
./deploy.sh                 # 전부
./deploy.sh portal proxy    # 일부만
```

`deploy.sh` 는 순서를 압니다 — 포털이 먼저(앱들이 등록해야 하니까),
프록시가 마지막(뒤가 떠 있어야 첫 요청부터 502 가 안 납니다).
프록시는 설정을 다시 읽히기까지 합니다(`nginx -s reload`) — 컨테이너가 이미 떠 있으면
compose 는 "Running" 이라고만 하고 아무것도 안 하기 때문입니다.

### 로그

```bash
docker compose -f portal/docker-compose.yml logs -f --tail 100
docker logs demo-proxy --tail 50
```

### 백업

백업할 것은 **`portal/data` 하나뿐**입니다 (계정 · 서비스 · 대화 기록).
나머지는 다시 만들 수 있습니다.

```bash
tar czf portal-$(date +%F).tgz portal/data
```

체험판이라면 그것마저 필요 없습니다. `./demo.sh` 를 다시 돌리면 처음 상태로 돌아옵니다.

### 체험판을 손볼 일이 생기면

**웹에서 누르는 것은 막혀 있습니다.** 방문자와 만든 사람을 화면에서 구분하지
않기로 했기 때문입니다 — 구분하려면 「이 계정만은 통과」 같은 예외를 두어야
하고, 그 순간 비밀번호 하나가 안전장치 전부가 됩니다.

대신 **보는 것은 전부 열려 있습니다.** 이력 · AI 사용량 · 사용자 명부 ·
서비스 목록은 `demo` 계정으로 그냥 보입니다. 실제로 손이 필요한 일은
이 정도인데, 전부 서버에서 한 줄입니다.

| 하고 싶은 일 | 명령 |
|---|---|
| 지금 무슨 일이 일어나는지 | `docker logs -f demo-portal --tail 50` |
| 챗이 왜 안 되는지 | `docker logs demo-portal 2>&1 \| grep -i error \| tail` |
| 이번 달 얼마나 썼는지 | 화면 → 관리 → AI 사용량 (로그인만 하면 보입니다) |
| 챗 횟수 제한 풀기 | `docker exec demo-portal python -c "import sqlite3;sqlite3.connect('data/demo.db').execute('DELETE FROM demo_chat').connection.commit()"` |
| 처음 상태로 되돌리기 | `./demo.sh` 다시 (데이터가 있으면 그대로 두고, 없으면 새로 만듭니다) |
| 아주 처음부터 | `docker compose -f portal/docker-compose.yml down` 후 `portal/data` 지우고 `./demo.sh` |
| 서비스 켜고 끄기 | 손댈 일이 없습니다. 포털이 뜰 때 등록된 것을 자동으로 켭니다 |

### 디스크

```bash
docker system df
docker image prune -f        # 옛 이미지 정리
```

빌드를 자주 하면 이미지가 쌓입니다. 20GB 서버라면 한 달에 한 번쯤 정리하세요.

---

## 7. 잘 안 될 때

| 증상 | 볼 곳 |
|---|---|
| 브라우저가 502 | 뒤 컨테이너가 죽었다. `docker ps` · `docker logs <이름>` |
| 앱이 관리자 화면에 안 뜬다 | 토큰이 다르다. `./setup.sh` 다시 → `./deploy.sh` |
| 큰 파일에서 413 | nginx 두 곳(**호스트**와 `proxy/conf.d/portal.conf`)의 `client_max_body_size` |
| 로그인이 자꾸 풀린다 | `COOKIE_SECURE` 가 실제 접속 방식(http/https)과 맞는지 |
| 챗만 안 된다 | `portal/.env` 의 키 · `docker logs portal` 에 공급자 오류 |
| 화면을 고쳤는데 안 바뀐다 | 캐시가 아니라 **컨테이너 안의 옛 파일**이다. `./deploy.sh <앱>` |
| 큰 엑셀을 올리면 컨테이너가 죽는다 | 메모리 부족. `mem_limit` 또는 서버 등급을 올린다 |

`./preflight.sh` 를 돌리면 위의 흔한 것들을 한 번에 훑어 줍니다.
