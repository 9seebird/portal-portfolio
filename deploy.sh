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

# ── 컨테이너가 옛 것을 붙들고 있나 ───────────────────────────
#
# 바인드 마운트는 **경로가 아니라 그때의 inode** 에 걸린다.
#
#   · 파일 하나를 붙인 경우 (./nginx.conf:/etc/nginx/conf.d/default.conf)
#     git pull 은 파일을 고쳐 쓰지 않는다. **새로 쓰고 이름을 바꿔 단다.**
#     그러면 inode 가 바뀌고, 컨테이너는 이미 사라진 옛 파일을 계속 본다.
#   · 폴더를 붙인 경우도 폴더가 통째로 새로 생기면(재클론·이동) 같다.
#
# 이게 고약한 이유는 어느 것도 이상을 알려주지 않기 때문이다.
#   · docker inspect 의 마운트 경로는 **맞게** 보인다
#   · git status 는 깨끗하고, git pull 도 정상이다
#   · 컨테이너는 healthy 다
#   · nginx -s reload 로도 안 풀린다 — 읽는 파일 자체가 옛것이다
#   · docker compose up -d 도 소용없다. compose 는 **서비스 정의**가
#     바뀌었는지만 본다. 붙인 파일의 내용이 바뀐 것은 보지 않는다.
# 실제로 이것 때문에 화면은 새것인데 API 만 404 인 채로 오래 있었다.
#
# 그래서 호스트와 컨테이너가 **같은 것을 보고 있는지** 직접 맞춰 본다.
# 다르면 아래에서 컨테이너를 다시 만든다. 그것 말고는 푸는 방법이 없다.
mount_drift() {              # $1 = 컨테이너 이름. 어긋난 것을 찍는다.
  local ct="$1" src dst a b
  docker inspect "$ct" --format \
    '{{range .Mounts}}{{if eq .Type "bind"}}{{.Source}}|{{.Destination}}{{println}}{{end}}{{end}}' \
    2>/dev/null | while IFS='|' read -r src dst; do
      [ -n "$src" ] || continue
      if [ -d "$src" ]; then
        # 폴더는 안에 든 이름만 맞춘다. 내용까지 다 읽으면 느리다
        # (매뉴얼 이미지가 17MB 다).
        a=$(ls -A -- "$src" 2>/dev/null | sort | md5sum)
        b=$(docker exec "$ct" sh -c "ls -A -- '$dst' 2>/dev/null" | sort | md5sum)
      elif [ -f "$src" ]; then
        # 파일은 내용을 맞춘다. **설정 파일이 여기 걸린다.**
        a=$(md5sum < "$src" 2>/dev/null)
        b=$(docker exec "$ct" sh -c "cat -- '$dst' 2>/dev/null" | md5sum)
      else
        continue
      fi
      [ "$a" != "$b" ] && echo "$src"
    done
  return 0
}

# ── 레포 전체를 한 번 당긴다 ─────────────────────────────────
# 서비스 폴더마다 .git 이 있던 시절의 잔재가 아래에 남아 있는데,
# 지금은 레포가 **하나**다. 그러니 여기서 한 번만 당기면 된다.
#   ./deploy.sh --no-pull   당기지 않고 지금 파일 그대로 띄운다
PULL=1
ARGS=()
for a in "$@"; do
  case "$a" in
    --no-pull) PULL=0 ;;
    # ★ 탭 자동완성이 넣어 주는 './it-asset/' 을 'it-asset' 으로 되돌린다.
    #   그대로 두면 폴더 경로가 '$ROOT/./it-asset/' 가 되어, 컨테이너가
    #   적어 둔 폴더와 글자가 달라진다. 그러면 내가 띄운 것을 남의 것으로
    #   착각하고 "이름 충돌" 로 멈춘다.
    *) a="${a#./}"; ARGS+=("${a%%/}") ;;
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
    #
    # ★ proxy 만 그런 것이 아니다. it-guide 도 nginx 를 쓴다.
    #   그리고 compose 는 depends_on 같은 것만 바뀌면 "바뀐 것 없음" 으로
    #   보고 컨테이너를 그대로 둔다. 그러면 설정 파일은 새것인데 nginx 는
    #   옛 설정으로 계속 돈다. **컨테이너는 healthy 인데 새 경로만 404** 인,
    #   원인을 짐작하기 어려운 상태가 된다.
    NGINX_CT=""
    [ "$name" = "proxy" ]    && NGINX_CT="demo-proxy"
    [ "$name" = "it-guide" ] && NGINX_CT="demo-guide-web"
    if [ -n "$NGINX_CT" ]; then
      # 설정을 다시 읽히기 **전에** 본다. 옛 파일을 보고 있으면
      # reload 를 아무리 해도 옛것을 다시 읽을 뿐이다.
      DRIFT="$(mount_drift "$NGINX_CT" || true)"
      if [ -n "$DRIFT" ]; then
        echo "  △ 컨테이너가 옛 것을 붙들고 있습니다 — 다시 만듭니다"
        echo "$DRIFT" | sed 's/^/      /'
        docker compose up -d --force-recreate
        if [ -n "$(mount_drift "$NGINX_CT" || true)" ]; then
          echo "  ✗ 다시 만들었는데도 그대로입니다. 마운트 경로를 확인하세요."
          FAILED+=("$name (마운트 어긋남)")
        else
          echo "  ✓ 컨테이너를 다시 만들어 지금 파일을 보게 했습니다"
        fi
      fi
      if docker exec "$NGINX_CT" nginx -t; then
        docker exec "$NGINX_CT" nginx -s reload >/dev/null 2>&1
        echo "  ✓ nginx 설정 다시 읽음 ($NGINX_CT)"
      else
        echo "  ✗ nginx 설정에 문제가 있어 그대로 둡니다. ($NGINX_CT)"
        echo "      고친 뒤 다시 실행하세요. 지금은 옛 설정으로 돌고 있습니다."
        FAILED+=("$name (설정 오류)")
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
