#!/usr/bin/env bash
# =====================================================================
# 배포 스크립트. /srv/portal/ 에 두고 쓴다.
#
#   ./deploy.sh              전부
#   ./deploy.sh portal       하나만
#   ./deploy.sh portal ai-report
#
# 각 서비스 폴더에 docker-compose.yml 이 있으면 대상으로 잡는다.
# =====================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NET="demo-net"

# ── 레포 전체를 한 번 당긴다 ─────────────────────────────────
# 서비스 폴더마다 .git 이 있던 시절의 잔재가 아래에 남아 있는데,
# 지금은 레포가 **하나**다. 그러니 여기서 한 번만 당기면 된다.
#   ./deploy.sh --no-pull   당기지 않고 지금 파일 그대로 띄운다
PULL=1
ARGS=()
for a in "$@"; do
  case "$a" in
    --no-pull) PULL=0 ;;
    *) ARGS+=("$a") ;;
  esac
done
set -- "${ARGS[@]+"${ARGS[@]}"}"

if [ "$PULL" = "1" ] && [ -d "$ROOT/.git" ]; then
  echo "▸ git pull"
  BEFORE="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo none)"
  if git -C "$ROOT" pull --ff-only; then
    AFTER="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo none)"

    # ★ 당긴 뒤에 setup 을 부른다. 순서가 반대면 안 된다.
    #
    #   전에는 「setup.sh 먼저, 그다음 deploy.sh」라고 안내했는데,
    #   deploy.sh 가 맨 앞에서 당기기 때문에 **새 앱은 setup 이 끝난 뒤에야
    #   도착한다.** 그래서 앱을 새로 붙인 커밋을 받으면 늘 이렇게 됐다.
    #
    #       ./setup.sh   → 그 앱이 아직 없어서 .env 를 안 만듦
    #       ./deploy.sh  → 당겨 오고 나서 띄우려다 .env 가 없어 실패
    #       ./setup.sh   → 이제야 만듦
    #       ./deploy.sh  → 됨
    #
    #   사람이 순서를 외우게 하는 대신 여기서 부른다. setup 은 이미 있는
    #   .env 를 건드리지 않으므로 매번 불러도 안전하다.
    if [ "$BEFORE" != "$AFTER" ] && [ -x "$ROOT/setup.sh" ]; then
      echo "▸ 받은 것이 있어 setup.sh 를 돌립니다 (새 앱의 .env·토큰)"
      "$ROOT/setup.sh" || { echo "  ✗ setup.sh 실패"; exit 1; }
    fi
  else
    echo "  ✗ 당기지 못했습니다."
    # git 이 실제로 뭐라고 했는지를 보고 갈라 준다.
    # (예전에는 계정 이름부터 봤는데, 원격이 HTTPS 로 바뀐 뒤로는
    #  맞지도 않는 ssh 별명 얘기를 먼저 꺼내서 엉뚱한 곳을 뒤지게 했다.)
    if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
      echo "      → 서버에서 직접 고친 파일이 있습니다:"
      git -C "$ROOT" status --short | sed 's/^/          /'
      echo "        버려도 되면  git -C $ROOT checkout -- <파일>"
    else
      echo "      → 네트워크나 접근 권한을 보세요."
      echo "        git -C $ROOT remote -v"
    fi
    exit 1
  fi
fi

# 공용 네트워크가 없으면 만든다. 없으면 컨테이너들이 서로를 못 찾는다.
docker network inspect "$NET" >/dev/null 2>&1 || {
  echo "▸ 네트워크 $NET 생성"
  docker network create "$NET"
}

# 대상 결정
if [ $# -gt 0 ]; then
  TARGETS=("$@")
else
  TARGETS=()
  for d in "$ROOT"/*/; do
    name="$(basename "$d")"
    # 밑줄로 시작하는 폴더는 작업용·참고용이다. 띄울 대상이 아니다.
    case "$name" in _*) continue ;; esac
    [ -f "${d}docker-compose.yml" ] && TARGETS+=("$name")
  done
fi

# 순서가 중요하다.
#
#   portal 이 맨 처음   앱들은 뜨자마자 포털에 "나 여기 있다"고 등록한다.
#                       포털이 아직 없으면 그 등록이 실패하고, 그 앱만
#                       관리자 화면에 안 뜬다. 화면에는 아무 단서도 없다.
#   proxy 가 맨 마지막   뒤쪽 서비스가 먼저 떠 있어야 첫 요청부터 502 가 안 난다.
ORDERED=()
for t in "${TARGETS[@]}"; do [ "$t" = "portal" ] && ORDERED+=("$t"); done
for t in "${TARGETS[@]}"; do
  case "$t" in portal|proxy) ;; *) ORDERED+=("$t") ;; esac
done
for t in "${TARGETS[@]}"; do [ "$t" = "proxy" ] && ORDERED+=("$t"); done

# 하나가 실패해도 나머지는 계속 올린다.
# 중간에 멈춰 버리면 "리포트가 안 뜨네" 하고 봤더니 포털도 안 떠 있는
# 상황이 된다. 실패한 것만 모아 뒤에서 알려준다.
FAILED=()

for name in "${ORDERED[@]}"; do
  dir="$ROOT/$name"
  if [ ! -f "$dir/docker-compose.yml" ]; then
    echo "✗ $name — docker-compose.yml 이 없습니다. 건너뜁니다."
    continue
  fi

  echo ""
  echo "════════════════════════════════════════"
  echo "▸ $name"
  echo "════════════════════════════════════════"

  cd "$dir"

  if [ -d .git ]; then
    echo "  git pull"
    git pull --ff-only || echo "  (pull 실패 — 로컬 변경이 있는지 확인하세요)"
  fi

  # .env 가 필요한데 없으면 띄우지 않는다.
  # 없는 채로 뜨면 JWT_SECRET 이 비어 첫 요청부터 500 이 난다.
  if [ -f .env.example ] && [ ! -f .env ]; then
    echo "  ✗ .env 가 없습니다. .env.example 을 복사해 값을 채우세요."
    FAILED+=("$name (.env 없음)")
    continue
  fi

  # 같은 이름의 컨테이너를 다른 프로젝트가 쥐고 있으면 여기서 멈춘다.
  #
  # container_name 은 도커 전체에서 유일해야 한다. 예전에 다른 폴더에서
  # 띄워 둔 컨테이너가 같은 이름을 쓰고 있으면 build 까지 다 끝난 뒤에
  # "Conflict. The container name /portal is already in use" 로 실패한다.
  # 무엇이 쥐고 있는지 먼저 알려주는 편이 낫다.
  CONFLICT=0
  for cname in $(grep -oP '^\s*container_name:\s*\K[A-Za-z0-9_.-]+' docker-compose.yml); do
    owner=$(docker inspect "$cname" \
      --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' 2>/dev/null || true)
    [ -z "$owner" ] && continue                 # 그런 컨테이너가 없다 = 정상
    [ "$owner" = "$dir" ] && continue           # 이 폴더 것이다 = 정상 (재배포)
    echo "  ✗ '$cname' 이름을 다른 곳에서 쓰고 있습니다."
    echo "      쓰는 곳 : ${owner:-(compose 로 만든 것이 아님)}"
    echo "      정리    : docker rm -f $cname"
    CONFLICT=1
  done
  if [ "$CONFLICT" = "1" ]; then
    FAILED+=("$name (컨테이너 이름 충돌)")
    continue
  fi

  if docker compose up -d --build; then
    echo "  ✓ $name"

    # ── 프록시는 설정을 다시 읽혀야 한다 ────────────────────────
    # conf.d 와 apps 는 볼륨으로 붙어 있어서 파일은 바로 보이지만,
    # nginx 는 뜰 때 한 번만 읽는다. 컨테이너가 이미 떠 있으면 compose 는
    # "Running" 이라고만 하고 아무것도 하지 않는다. 그래서 앱 conf 를
    # 새로 넣어도 그 경로가 404 로 남는다.
    if [ "$name" = "proxy" ]; then
      if docker exec demo-proxy nginx -t; then
        docker exec demo-proxy nginx -s reload >/dev/null 2>&1
        echo "  ✓ nginx 설정 다시 읽음"
      else
        echo "  ✗ nginx 설정에 문제가 있어 그대로 둡니다."
        echo "      고친 뒤 다시 실행하세요. 지금은 옛 설정으로 돌고 있습니다."
        FAILED+=("proxy (설정 오류)")
      fi
    fi
  else
    echo "  ✗ $name — 빌드 또는 실행 실패"
    FAILED+=("$name")
  fi
done

echo ""
echo "════════════════════════════════════════"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

if [ ${#FAILED[@]} -gt 0 ]; then
  echo ""
  echo "실패: ${FAILED[*]}"
  echo "  로그 확인:  docker compose -f <폴더>/docker-compose.yml logs --tail 50"
  exit 1
fi

# 실제로 어느 포트로 열렸는지는 proxy/.env 가 안다.
# 여기 「http://localhost/」 라고 못 박아 두면, 8090 으로 띄운 사람이
# 열리지도 않는 주소를 붙잡고 「안 뜬다」고 한다.
PUB="$(sed -n 's/^PROXY_PUBLISH=//p' "$ROOT/proxy/.env" 2>/dev/null | head -1)"
case "$PUB" in
  127.0.0.1:*) URL="앞의 nginx 를 거쳐 들어오세요 (${PUB%:80})" ;;
  *:80)        URL="http://localhost:${PUB%:80}/" ;;
  *)           URL="http://localhost/" ;;
esac
echo ""
echo "확인:  $URL"
