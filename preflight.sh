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

line "80번 포트"
# ss 가 없는 서버도 있어서 두 가지로 본다
if command -v ss >/dev/null 2>&1; then LIST=$(ss -ltnp 2>/dev/null)
elif command -v netstat >/dev/null 2>&1; then LIST=$(netstat -ltnp 2>/dev/null)
else LIST=""; fi
if [ -z "$LIST" ]; then
  warn "포트 확인 도구(ss/netstat)가 없습니다. 직접 확인하세요."
elif printf '%s' "$LIST" | grep -qE '(:80)\s'; then
  bad "80번을 이미 쓰고 있습니다:"
  printf '%s' "$LIST" | grep -E '(:80)\s' | sed 's/^/      /'
  echo "      → 그 서비스를 옮기거나, proxy/docker-compose.yml 의"
  echo '        ports 를 "8090:80" 처럼 바꾸세요.'
else
  ok "80번이 비어 있습니다."
fi

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
tok_portal=$(grep -oP '^AUDIT_TOKEN=\K.*' "$HERE/portal/.env" 2>/dev/null | tr -d '\r')
if [ -z "$tok_portal" ]; then
  bad "portal/.env 에 AUDIT_TOKEN 이 없습니다."
elif [ "$tok_portal" = "change-this-shared-token" ]; then
  bad "AUDIT_TOKEN 이 예시값 그대로입니다. 임의의 긴 문자열로 바꾸세요."
else
  ok "portal/.env 에 설정됨"
  for f in it-asset/docker-compose.yml ai-report/docker-compose.yml; do
    [ -f "$HERE/$f" ] || continue
    t=$(grep -oP 'AUDIT_TOKEN[:=]\s*\K\S+' "$HERE/$f" | tr -d '"' | head -1)
    if [ -n "$t" ] && [ "$t" != "$tok_portal" ]; then
      bad "$f 의 AUDIT_TOKEN 이 포털과 다릅니다. 자동 등록·이력이 조용히 실패합니다."
    elif [ -n "$t" ]; then
      ok "$f 일치"
    fi
  done
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
