# 호스트 nginx — 실제로 어떻게 붙어 있나

> **2026-08-12 확인.** 옛 서비스를 내리고 그 위에 얹은 서버라, 처음 문서와
> 실제가 달랐습니다. 여기 적힌 것이 **지금 서버에 있는 그대로**입니다.

## 길

```
브라우저
  │
  ├─ /etc/nginx/sites-available/main.conf          ← 뼈대. server 블록 셋
  │    · 80 + 도메인   → https 로 보냄
  │    · 80 + IP       → 그대로 동작 (인증서가 IP는 커버 못 함)
  │    · 443 + 도메인  → 본 서비스
  │    셋 다 아래 한 줄을 include 한다
  │
  ├─ /etc/nginx/snippets/portal-common.conf        ← 공통 설정
  │    · proxy_set_header 넷 (Host · X-Real-IP · X-Forwarded-For/Proto)
  │    · client_max_body_size 500m   ← 크기 제한은 **여기 한 곳**
  │    · client_body_timeout  600s
  │    · location = /_portal_auth   (호스트에서 권한을 물을 때 쓰는 내부 창구)
  │    · include /srv/portal/nginx/*.conf   ← 아래 폴더를 통째로
  │
  ├─ /srv/portal/nginx/portal-chat.conf     ← location / → 127.0.0.1:8081
  │    · proxy_buffering off / proxy_cache off  (챗이 한 글자씩 내려와야 함)
  │    · proxy_read_timeout 300s
  │    · **크기 제한을 두지 않는다** — 위 공통 값을 그대로 쓴다
  │
  └─ 127.0.0.1:8081  =  proxy 컨테이너
       · proxy/conf.d/portal.conf   150m
       · proxy/apps/<서비스ID>.conf  앱마다 권한·크기·시간
```

## 누가 무엇을 고칠 수 있나

| 파일 | 주인 | 고칠 때 |
|---|---|---|
| `sites-available/main.conf` | root | **sudo 필요.** 도메인·인증서 바꿀 때만 |
| `snippets/portal-common.conf` | root | **sudo 필요.** 공통 크기·시간 |
| `/srv/portal/nginx/*.conf` | **portal** | **sudo 없이 고칩니다** |
| `proxy/apps/*.conf` | portal | `./deploy.sh proxy` |

반영은 어느 것이든 마지막에 한 줄입니다 (이것만 sudo).

```bash
sudo nginx -t && sudo systemctl reload nginx
```

## 새 앱을 붙일 때 — **호스트는 안 건드립니다**

호스트는 `location /` 하나로 전부 8081 에 넘깁니다. 앱별 경로는 그 안쪽
proxy 컨테이너가 가릅니다. 그래서 새 앱은 이것만 하면 됩니다.

```powershell
cd proxy; .\new-app.ps1 <서비스ID>; cd ..
.\deploy.ps1 proxy
```

호스트 nginx 도 `sudo` 도 필요 없습니다.

## 크기 제한은 **한 곳에서만**

```
호스트  snippets/portal-common.conf   500m   ← 통로. 크게 한 번만
안쪽    proxy/apps/<앱>.conf                 ← 문지기. 앱마다
```

2026-08-12 에 63MB 엑셀이 413 으로 막혔는데, 원인은
`/srv/portal/nginx/portal-chat.conf` 의 `location /` 안에 **20m 가
따로 적혀 있어서**였습니다. nginx 는 가장 안쪽 값을 쓰기 때문에, 공통을
500m 로 올려도 소용이 없었습니다. 그 줄은 지웠습니다.

**앞으로 크기를 바꿀 일이 생기면 `portal-common.conf` 하나만 보세요.**

## 이 폴더의 파일들

서버에 있는 것과 **같은 내용의 사본**입니다. 서버가 날아가도 여기서
되살릴 수 있게 두는 것이지, 서버가 이 파일을 읽는 것은 아닙니다.

| 파일 | 서버의 어디 |
|---|---|
| `portal-chat.conf` | `/srv/portal/nginx/portal-chat.conf` |
| `portal-common.conf` | `/etc/nginx/snippets/portal-common.conf` |

고쳤으면 **서버에도 같이 반영**해야 합니다. 자동으로 따라가지 않습니다.
