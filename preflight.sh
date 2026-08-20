#!/usr/bin/env bash
# =====================================================================
# 서버가 배포를 받을 준비가 됐는지 미리 본다. **아무것도 바꾸지 않는다.**
#
#   ./preflight.sh
#
# 파일을 다 올린 뒤, deploy.sh 를 돌리기 **전에** 한 번 실행한다.
# 여기서 걸리는 것들은 배포 도중에 만나면 원인을 찾기 번거로운 것들이다.
# =====================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NET="demo-net"
OK=0; WARN=0; BAD=0

ok()   { echo "  ✓ $1"; OK=$((OK+1)); }
warn() { echo "  △ $1"; WARN=$((WARN+1)); }
bad()  { echo "  ✗ $1"; BAD=$((BAD+1)); }
line() { echo ""; echo "── $1 ──"; }

line "도커"
if command -v docker >/dev/null 2>&1; then
  ok "docker $(docker --version | awk '{print $3}' | tr -d ,)"
  docker info >/dev/null 2>&1 && ok "도커 데몬 응답함" \
    || bad "도커 데몬에 붙지 못합니다. sudo 가 필요하거나 서비스가 꺼져 있습니다."
else
  bad "docker 가 없습니다."
fi
if docker compose version >/dev/null 2>&1; then
  ok "docker compose $(docker compose version --short 2>/dev/null)"
else
  bad "docker compose (v2) 가 없습니다. 옛 docker-compose 는 이 파일들과 다르게 동작할 수 있습니다."
fi

line "프록시가 쓸 포트"
# ★ 80 을 하드코딩하면 안 된다.
#
#   서버에는 앞에 호스트 nginx 가 있고, 그것이 80·443 을 쥐고 도메인과
#   인증서를 담당한다. 이 컨테이너는 그 **뒤에** 127.0.0.1:8081 로 선다.
#   그런데 예전 검사는 무조건 80 을 보고 "이미 쓰고 있습니다 ✗" 를 냈다 —
#   정상인 상태를 문제라고 한 것이다. 그래서 늘 문제 1건을 달고 살았고,
#   그러면 진짜 문제가 났을 때도 그러려니 하고 지나치게 된다.
#
#   봐야 할 것은 **proxy/.env 가 실제로 열겠다고 한 그 포트**다.
PUB=$(grep -oP '^PROXY_PUBLISH=\K.*' "$HERE/proxy/.env" 2>/dev/null | tr -d '\r')
PUB=${PUB:-80:80}
# "127.0.0.1:8081:80" 이면 8081, "8090:80" 이면 8090 — 뒤에서 두 번째 토막이다.
HOSTPORT=$(printf '%s' "$PUB" | awk -F: '{print $(NF-1)}')

if command -v ss >/dev/null 2>&1; then LIST=$(ss -ltnp 2>/dev/null)
elif command -v netstat >/dev/null 2>&1; then LIST=$(netstat -ltnp 2>/dev/null)
else LIST=""; fi

if [ -z "$HOSTPORT" ]; then
  warn "proxy/.env 의 PROXY_PUBLISH 를 읽지 못했습니다 ($PUB)."
elif [ -z "$LIST" ]; then
  warn "포트 확인 도구(ss/netstat)가 없습니다. 직접 확인하세요."
elif ! printf '%s' "$LIST" | grep -qE "[:.]${HOSTPORT}[[:space:]]"; then
  ok "$HOSTPORT 번이 비어 있습니다 (PROXY_PUBLISH=$PUB)"
elif docker ps --format '{{.Names}}' 2>/dev/null | grep -qx demo-proxy; then
  ok "$HOSTPORT 번은 이미 뜬 demo-proxy 가 씁니다 — 다시 배포하면 이어받습니다"
else
  bad "$HOSTPORT 번을 다른 것이 쓰고 있습니다:"
  printf '%s' "$LIST" | grep -E "[:.]${HOSTPORT}[[:space:]]" | sed 's/^/      /'
  echo "      → 그 서비스를 옮기거나, proxy/.env 의 PROXY_PUBLISH 를 바꾸세요."
fi

# 앞단 nginx 를 두는 방식(127.0.0.1:…)이면 80 은 그 nginx 몫이라 차 있는 것이 정상이다.
case "$PUB" in
  127.0.0.1:*|localhost:*)
    if printf '%s' "$LIST" | grep -qE '[:.]80[[:space:]]'; then
      ok "80 번은 앞단 nginx 가 쓰고 있습니다 (이 구성에서는 정상)"
    else
      warn "80 번이 비어 있습니다. 앞단 nginx 가 꺼져 있으면 도메인으로 안 들어옵니다."
      echo "      → sudo systemctl status nginx"
    fi
    ;;
esac

line "네트워크"
docker network inspect "$NET" >/dev/null 2>&1 \
  && ok "$NET 있음" \
  || warn "$NET 없음 — deploy.sh 가 알아서 만듭니다."

line "컨테이너 이름 충돌"
CONFLICT=0
for compose in "$HERE"/*/docker-compose.yml; do
  [ -f "$compose" ] || continue
  app=$(basename "$(dirname "$compose")")
  for cname in $(grep -oP '^\s*container_name:\s*\K[A-Za-z0-9_.-]+' "$compose"); do
    owner=$(docker inspect "$cname" \
      --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' 2>/dev/null || true)
    if [ -n "$owner" ] && [ "$owner" != "$(dirname "$compose")" ]; then
      bad "'$cname' ($app) 이름을 다른 곳이 쓰고 있습니다: $owner"
      echo "      → docker rm -f $cname"
      CONFLICT=1
    fi
  done
done
[ "$CONFLICT" = "0" ] && ok "충돌 없음"

line "설정 파일"
for f in portal/.env; do
  [ -f "$HERE/$f" ] && ok "$f 있음" || bad "$f 없음 — 서버에는 git 으로 안 따라옵니다. 따로 올리세요."
done
[ -f "$HERE/it-asset/backend/.env.deploy" ] && ok "it-asset/backend/.env.deploy 있음" \
  || warn "it-asset/backend/.env.deploy 없음 (자산관리를 쓸 거면 필요)"

# 세 곳의 토큰이 같아야 자동 등록·이력 전송이 된다. 다르면 조용히 실패한다.
line "AUDIT_TOKEN 일치"
# ★ docker-compose.yml 을 보면 안 된다.
#
#   compose 에는 이제 실제 값이 아니라 `${AUDIT_TOKEN:?...}` 자리표시자만 있다.
#   그걸 그대로 읽어 포털 토큰과 비교하니 늘 "다릅니다 ✗" 가 나왔다.
#   진짜 값은 **앱마다의 .env** 에 있고, setup 이 그걸 채운다.
tok_portal=$(grep -oP '^AUDIT_TOKEN=\K.*' "$HERE/portal/.env" 2>/dev/null | tr -d '\r')
if [ -z "$tok_portal" ]; then
  bad "portal/.env 에 AUDIT_TOKEN 이 없습니다."
  echo "      → ./setup.sh 를 돌리면 만들어집니다."
elif [ "$tok_portal" = "change-this-shared-token" ]; then
  bad "AUDIT_TOKEN 이 예시값 그대로입니다. 임의의 긴 문자열로 바꾸세요."
else
  ok "portal/.env 에 설정됨"
  MISS=0
  # compose 가 AUDIT_TOKEN 을 쓰는 앱만 본다. 앱이 늘어도 이 줄은 그대로다.
  while IFS= read -r cfg; do
    app="$(basename "$(dirname "$cfg")")"
    [ "$app" = "portal" ] && continue
    grep -q 'AUDIT_TOKEN' "$cfg" || continue
    t=$(grep -oP '^AUDIT_TOKEN=\K.*' "$(dirname "$cfg")/.env" 2>/dev/null | tr -d '\r')
    if [ -z "$t" ]; then
      bad "$app/.env 에 AUDIT_TOKEN 이 없습니다. 자동 등록·이력이 조용히 실패합니다."
      echo "      → ./setup.sh"
      MISS=1
    elif [ "$t" != "$tok_portal" ]; then
      bad "$app/.env 의 AUDIT_TOKEN 이 포털과 다릅니다. 자동 등록·이력이 조용히 실패합니다."
      MISS=1
    fi
  done < <(find "$HERE" -maxdepth 2 -name docker-compose.yml 2>/dev/null | sort)
  [ "$MISS" = "0" ] && ok "모든 앱의 .env 가 포털과 같은 값"
fi

line "줄바꿈 형식"
# 윈도우에서 편집한 파일이 CRLF 로 오면 스크립트와 설정이 이상하게 동작한다
CR=0
while IFS= read -r f; do
  grep -qU $'\r' "$f" 2>/dev/null && { bad "CRLF: ${f#$HERE/}"; CR=1; }
done < <(find "$HERE" -maxdepth 3 \( -name '*.sh' -o -name '*.conf' -o -name '.env' -o -name 'Dockerfile' \) 2>/dev/null)
[ "$CR" = "0" ] && ok "전부 LF (리눅스 형식)"

line "실행 권한"
NOX=0
for f in "$HERE"/*.sh "$HERE"/proxy/*.sh; do
  [ -f "$f" ] || continue
  [ -x "$f" ] || { warn "실행 권한 없음: ${f#$HERE/}"; NOX=1; }
done
[ "$NOX" = "1" ] && echo "      → chmod +x *.sh proxy/*.sh"
[ "$NOX" = "0" ] && ok "모든 .sh 실행 가능"

line "주인 전용 입구(8082)가 밖으로 새지 않는가"
# 이 문에는 체험판 가드가 없다. 안전장치는 비밀번호가 아니라 **네트워크**이므로,
# 127.0.0.1 이 앞에 붙어 있는지가 전부다. 이 한 줄이 빠지면 아무나 데모를 고친다.
CFG="$HERE/proxy/docker-compose.yml"
if [ ! -f "$CFG" ]; then
  warn "proxy/docker-compose.yml 이 없습니다."
elif ! grep -q '8082' "$CFG"; then
  warn "8082 입구가 없습니다 (02-admin.conf 를 쓰지 않는 설정인 듯합니다)."
elif grep -Eq '^[[:space:]]*-[[:space:]]*"?127\.0\.0\.1:8082:8082"?[[:space:]]*$' "$CFG"; then
  ok "compose 에 127.0.0.1 로만 열려 있습니다"
else
  bad "8082 가 127.0.0.1 없이 열려 있습니다 — 아무나 데모를 고칠 수 있습니다."
  echo "      → proxy/docker-compose.yml 의 ports 를  \"127.0.0.1:8082:8082\"  로 고치세요."
fi

# 실제로 떠 있는 것도 본다. 파일이 맞아도 옛 컨테이너가 그대로 돌 수 있다.
if docker inspect demo-proxy >/dev/null 2>&1; then
  BIND="$(docker port demo-proxy 8082 2>/dev/null | head -1)"
  case "$BIND" in
    "")            warn "demo-proxy 가 8082 를 아직 열지 않았습니다 (다시 배포하면 열립니다)." ;;
    127.0.0.1:*)   ok "지금 뜬 컨테이너도 $BIND — 바깥에서 닿지 않습니다" ;;
    *)             bad "지금 뜬 컨테이너가 $BIND 로 열려 있습니다 — 즉시 다시 배포하세요."
                   echo "      → ./deploy.sh proxy" ;;
  esac
fi

# 호스트 nginx 가 실수로 8082 를 넘겨주고 있지 않은지. 이게 제일 흔한 뒷문이다.
if [ -d /etc/nginx ]; then
  HIT="$(grep -rl '8082' /etc/nginx 2>/dev/null | head -3)"
  if [ -n "$HIT" ]; then
    bad "호스트 nginx 설정에 8082 가 보입니다 — 주인 전용 입구가 인터넷에 노출됐을 수 있습니다."
    echo "$HIT" | sed 's/^/      /'
  else
    ok "호스트 nginx 는 8082 를 넘기지 않습니다"
  fi
fi

line "디스크"
avail=$(df -Pm "$HERE" | awk 'NR==2{print $4}')
[ "${avail:-0}" -gt 2000 ] && ok "여유 ${avail}MB" || warn "여유 ${avail}MB — 이미지 빌드에 2GB 쯤 듭니다."

echo ""
echo "════════════════════════════════════════"
echo "  통과 $OK · 주의 $WARN · 문제 $BAD"
if [ "$BAD" -gt 0 ]; then
  echo "  문제(✗)를 먼저 해결하고 ./deploy.sh 를 실행하세요."
  exit 1
fi
echo "  ./deploy.sh 를 실행해도 좋습니다."
