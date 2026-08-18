#!/usr/bin/env bash
# =====================================================================
# 처음 한 번 — 깃에서 받은 직후에 돌린다.
#
#   ./setup.sh              사내 서버 (호스트 nginx 뒤, 127.0.0.1:8081)
#   ./setup.sh --local      로컬 시험용 (80 을 그대로)
#
# 하는 일
#   1. .env.example 들을 .env 로 복사한다 (이미 있으면 건드리지 않는다)
#   2. JWT 서명키와 서비스 토큰을 만든다
#   3. **같은 서비스 토큰을 네 파일에 맞춰 넣는다**
#
# 3번이 이 스크립트가 있는 이유다. 토큰이 한 글자만 달라도 포털이 앱을
# 못 부르고 "Unauthorized" 만 돌아오는데, 화면에는 아무 단서가 없다.
# 사람이 손으로 맞추면 언젠가 반드시 어긋난다.
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")"

MODE="server"
[ "${1:-}" = "--local" ] && MODE="local"

say()  { printf '%s\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }

rand() { head -c 48 /dev/urandom | base64 | tr -d '\n=+/' | cut -c1-40; }

# ── 1. .env 만들기 ───────────────────────────────────────────
say ""
say "▸ .env 준비"
# ★ 폴더 이름을 적어 두지 않는다.
#   새 서비스를 붙일 때마다 이 목록을 고치게 하면 언젠가 반드시 빠뜨린다.
#   .env.example 이 있는 폴더는 전부 대상으로 본다.
CREATED=()
for d in */; do
  d="${d%/}"
  case "$d" in _*) continue ;; esac        # 작업용 폴더는 건너뛴다
  [ -f "$d/.env.example" ] || continue
  if [ -f "$d/.env" ]; then
    ok "$d/.env — 이미 있음 (건드리지 않음)"
  else
    cp "$d/.env.example" "$d/.env"
    CREATED+=("$d")
    ok "$d/.env — 새로 만듦"
  fi
done

# ★ 한 단 아래에 있는 것도 있다.
#   it-asset 은 백엔드가 자기 설정을 따로 쓴다 — it-asset/backend/.env.deploy.
#   위 반복문은 **최상위 폴더만** 보므로 이 파일이 안 만들어지고,
#   compose 의 `env_file:` 이 없는 파일을 가리켜 it-asset 만 조용히 실패한다.
#   내 PC 에는 예전에 만든 파일이 남아 있어서 안 보이고, **새로 받은 사람만**
#   걸린다 — 그래서 오래 못 찾았다.
for x in it-asset/backend/.env.deploy; do
  [ -f "$x.example" ] || continue
  if [ -f "$x" ]; then
    ok "$x — 이미 있음 (건드리지 않음)"
  else
    cp "$x.example" "$x"
    ok "$x — 새로 만듦"
  fi
done

# ── 2. 값 채우기 ─────────────────────────────────────────────
# 이미 쓰고 있는 값이 있으면 그걸 유지한다. 새로 만들면 로그인 세션이
# 전부 끊기고, 앱들과의 토큰도 다시 맞춰야 한다.
setval() {   # setval <파일> <키> <값>
  local f="$1" k="$2" v="$3"
  [ -f "$f" ] || return 0
  if grep -q "^${k}=" "$f"; then
    # 값이 비어 있을 때만 채운다
    if [ -z "$(sed -n "s/^${k}=//p" "$f" | head -1)" ]; then
      sed -i "s|^${k}=.*|${k}=${v}|" "$f"
      return 0
    fi
    return 1
  else
    printf '%s=%s\n' "$k" "$v" >> "$f"
    return 0
  fi
}

cur() { sed -n "s/^$2=//p" "$1" 2>/dev/null | head -1; }

say ""
say "▸ 비밀값"

JWT="$(cur portal/.env JWT_SECRET)"
if [ -z "$JWT" ] || [ "$JWT" = "change-this-to-a-long-random-string" ]; then
  JWT="$(rand)"
  sed -i "s|^JWT_SECRET=.*|JWT_SECRET=${JWT}|" portal/.env
  ok "JWT_SECRET 새로 만듦"
else
  ok "JWT_SECRET 그대로 둠"
fi

TOK="$(cur portal/.env AUDIT_TOKEN)"
if [ -z "$TOK" ] || [ "$TOK" = "change-this-shared-token" ]; then
  TOK="$(rand)"
  sed -i "s|^AUDIT_TOKEN=.*|AUDIT_TOKEN=${TOK}|" portal/.env
  ok "AUDIT_TOKEN 새로 만듦"
else
  ok "AUDIT_TOKEN 그대로 둠"
fi

# ★ 여기가 핵심 — 같은 값을 옆 앱들에 맞춰 넣는다.
#   portal 은 이 토큰의 주인이므로 건너뛴다. 나머지는 전부 맞춘다.
for d in */; do
  d="${d%/}"
  case "$d" in portal|proxy|_*) continue ;; esac
  [ -f "$d/.env" ] || continue
  if grep -q "^AUDIT_TOKEN=" "$d/.env"; then
    sed -i "s|^AUDIT_TOKEN=.*|AUDIT_TOKEN=${TOK}|" "$d/.env"
  else
    printf 'AUDIT_TOKEN=%s\n' "$TOK" >> "$d/.env"
  fi
  ok "$d/.env — 포털과 같은 토큰으로 맞춤"

  # 앱이 포털을 부를 주소. 같은 네트워크라 컨테이너 이름으로 부른다.
  # 비어 있으면 앱이 자기 등록을 건너뛰고 관리자 화면에 안 뜬다.
  #
  # ★ 줄이 **아예 없을 때도** 넣어 준다.
  #   전에는 "있으면 채운다" 였는데, 그러면 .env.example 에 그 줄을 안 적어 둔
  #   앱은 영영 비어 있게 된다. 실제로 it-asset 이 그래서 뜰 때마다
  #   "[포털 등록] PORTAL_API_URL 이 없어 건너뜁니다" 로 조용히 넘어가고 있었다.
  #   관리자 화면에 이미 보이니까 아무도 몰랐다 (전에 등록해 둔 것이 남아 있어서).
  if grep -q "^PORTAL_API_URL=" "$d/.env"; then
    if [ -z "$(sed -n 's/^PORTAL_API_URL=//p' "$d/.env" | head -1)" ]; then
      sed -i "s|^PORTAL_API_URL=.*|PORTAL_API_URL=http://demo-portal:8080|" "$d/.env"
      ok "$d/.env — PORTAL_API_URL 채움"
    fi
  else
    printf 'PORTAL_API_URL=http://demo-portal:8080\n' >> "$d/.env"
    ok "$d/.env — PORTAL_API_URL 넣음 (없었음)"
  fi
  # 서버에서는 개발 모드가 꺼져 있어야 한다.
  # 켜져 있으면 헤더가 없을 때 테스트 계정으로 통과한다.
  if grep -q "^DEV_MODE=" "$d/.env"; then
    cur_dev="$(sed -n 's/^DEV_MODE=//p' "$d/.env" | head -1)"
    if [ -z "$cur_dev" ] || { [ "$MODE" = "server" ] && [ "$cur_dev" != "false" ]; }; then
      sed -i "s|^DEV_MODE=.*|DEV_MODE=false|" "$d/.env"
      ok "$d/.env — DEV_MODE=false"
    fi
  else
    printf 'DEV_MODE=false\n' >> "$d/.env"
    ok "$d/.env — DEV_MODE=false 넣음 (없었음)"
  fi
done

# ── 3. 어디에 띄울지 ─────────────────────────────────────────
say ""
say "▸ 프록시 포트"
if [ "$MODE" = "local" ]; then
  PUB="80:80";            COOKIE=0; NOTE="로컬 — 80 을 그대로 씁니다"
else
  PUB="127.0.0.1:8081:80"; COOKIE=1; NOTE="서버 — 호스트 nginx 뒤에 섭니다"
fi
if [ -f proxy/.env ]; then
  if grep -q "^PROXY_PUBLISH=" proxy/.env; then
    sed -i "s|^PROXY_PUBLISH=.*|PROXY_PUBLISH=${PUB}|" proxy/.env
  else
    printf 'PROXY_PUBLISH=%s\n' "$PUB" >> proxy/.env
  fi
fi
ok "$NOTE  (PROXY_PUBLISH=$PUB)"

# HTTPS 로 들어오면 쿠키에 secure 를 붙여야 한다.
# http 인데 1 로 두면 쿠키가 저장되지 않아 로그인이 안 된다.
if grep -q "^COOKIE_SECURE=" portal/.env; then
  sed -i "s|^COOKIE_SECURE=.*|COOKIE_SECURE=${COOKIE}|" portal/.env
  ok "COOKIE_SECURE=${COOKIE}"
fi

# ── 4. 남은 것 ───────────────────────────────────────────────
say ""
KEY="$(cur portal/.env OPENAI_API_KEY)"
if [ -z "$KEY" ] || [[ "$KEY" == 발급받은* ]]; then
  warn "portal/.env 의 OPENAI_API_KEY 를 채우세요. (이것만은 사람이 넣어야 합니다)"
else
  ok "OPENAI_API_KEY 들어 있음"
fi

say ""
say "──────────────────────────────────────────────"
say "다음:"
say "  docker network create demo-net    # 처음 한 번만"
say "  ./deploy.sh                         # 전부 띄우기"
if [ "$MODE" = "server" ]; then
  say ""
  say "그리고 호스트 nginx 에 nginx/portal-chat.conf 의 내용을 넣고"
  say "  sudo nginx -t && sudo systemctl reload nginx"
fi
say ""
