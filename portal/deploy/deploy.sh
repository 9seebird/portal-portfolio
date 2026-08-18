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
    [ -f "${d}docker-compose.yml" ] && TARGETS+=("$(basename "$d")")
  done
fi

# proxy 는 맨 마지막에 올린다. 뒤쪽 서비스가 먼저 떠 있어야
# 첫 요청부터 502 가 나지 않는다.
ORDERED=()
for t in "${TARGETS[@]}"; do [ "$t" != "proxy" ] && ORDERED+=("$t"); done
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

echo ""
echo "확인:  curl -s localhost/health        → {\"ok\":true}"
echo "       브라우저에서 http://localhost/"
