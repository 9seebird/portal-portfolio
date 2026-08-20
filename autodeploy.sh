#!/usr/bin/env bash
# =====================================================================
# 자동 배포 — 깃에 새 커밋이 올라오면 받아서 띄운다.
#
#   /srv/portal/autodeploy.sh          평소 (타이머가 부른다)
#   /srv/portal/autodeploy.sh --force  새 커밋이 없어도 다시 띄운다
#   /srv/portal/autodeploy.sh --dry    무엇을 할지 보기만 한다
#
# 저장소를 받아 둔 그 계정으로 돈다 (지금 서버에서는 azureuser).
# 다른 계정으로 돌리면 파일 주인이 뒤섞여 다음 git pull 이 막힌다.
#
# ── 왜 깃허브 웹훅이 아니라 「물어보기」인가 ─────────────────────
# 웹훅은 깃허브가 서버를 부르는 방식이라, 바깥에서 들어오는 문을 하나 더
# 열고 서버 접속 열쇠를 깃허브에 맡겨야 한다. 포트폴리오 한 대에는 과하다.
# 이쪽은 서버가 몇 분에 한 번 「새 거 있나요」 하고 물어보기만 한다.
# 열어 둘 문도, 맡길 열쇠도 없다.
#
# ── 무작정 띄우지는 않는다 ──────────────────────────────────
# 자동 배포의 진짜 위험은 「깨진 것을 올렸는데 아무도 안 보고 있는 것」이다.
# 그래서 띄운 뒤 /health 를 두드려 보고, 대답이 없으면 **직전 커밋으로
# 되돌려 다시 띄운다.** 사이트가 죽은 채로 밤을 넘기지 않는 것이 목적이다.
# =====================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$ROOT/autodeploy.log"
LOCK="$ROOT/.autodeploy.lock"
HEALTH_TRIES=12          # 2초 간격 → 최대 24초 기다린다
FORCE=0; DRY=0
for a in "$@"; do
  case "$a" in
    --force) FORCE=1 ;;
    --dry)   DRY=1 ;;
    *) echo "모르는 옵션: $a"; exit 2 ;;
  esac
done

say(){ printf '%s  %s\n' "$(date '+%F %T')" "$1" | tee -a "$LOG"; }

# ── 겹쳐 돌지 않게 ──────────────────────────────────────────
# 배포가 2분 넘게 걸리는 사이에 타이머가 또 불러도 조용히 물러난다.
exec 9>"$LOCK"
flock -n 9 || { echo "$(date '+%F %T')  (앞 배포가 아직 돕니다 — 건너뜀)" >>"$LOG"; exit 0; }

cd "$ROOT" || exit 1

# ── 저장소 주인과 같은 계정인가 ─────────────────────────────
# 예전에는 여기서 계정 이름을 "portal" 로 못 박아 두었다. 그런 계정은
# 만들지 않았고, 서버는 azureuser 로 돈다 — 그래서 타이머를 걸어도
# 매번 첫 줄에서 죽었다. 이름을 적는 대신 **폴더 주인과 같은지**를 본다.
# 그러면 계정 이름이 무엇이든, 어느 서버로 옮기든 그대로 맞는다.
OWNER="$(stat -c %U "$ROOT/.git" 2>/dev/null || echo "")"
ME="$(id -un)"
if [ -n "$OWNER" ] && [ "$OWNER" != "$ME" ] && [ -z "${ALLOW_ANY_USER:-}" ]; then
  say "✗ 이 폴더의 주인은 $OWNER 인데 지금 $ME 로 돌고 있습니다."
  say "  그대로 두면 파일 주인이 섞여 다음 git pull 이 막힙니다."
  say "  → sudo -u $OWNER $ROOT/autodeploy.sh   (또는 ALLOW_ANY_USER=1)"
  exit 1
fi

# ── 서버에서 직접 고친 파일이 있으면 멈춘다 ────────────────────
# 여기서 --force 로 밀어 버리면 급하게 손본 것이 소리 없이 사라진다.
if [ -n "$(git status --porcelain)" ]; then
  say "✗ 서버에 커밋 안 된 변경이 있어 멈춥니다:"
  git status --short | sed 's/^/          /' | tee -a "$LOG"
  say "  (버릴 것이면  git checkout -- <파일>  후 다시)"
  exit 1
fi

# ── 새 커밋이 있나 ─────────────────────────────────────────
git fetch --quiet origin || { say "✗ git fetch 실패 (네트워크·열쇠 확인)"; exit 1; }
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
OLD="$(git rev-parse HEAD)"
NEW="$(git rev-parse "origin/$BRANCH")"

if [ "$OLD" = "$NEW" ] && [ "$FORCE" = 0 ]; then
  exit 0                      # 조용히. 로그를 더럽히지 않는다.
fi

say "── 새 커밋 $(git log --oneline -1 "$NEW" | cut -c1-60)"
if [ "$DRY" = 1 ]; then
  say "  (--dry: 여기까지만)"
  git --no-pager log --oneline "$OLD..$NEW" | sed 's/^/          /' | tee -a "$LOG"
  exit 0
fi

git pull --ff-only --quiet || { say "✗ git pull 실패"; exit 1; }

# ── 띄우기 ────────────────────────────────────────────────
# setup.sh 를 먼저 부른다. .env 는 깃에 없으므로, 앱을 새로 붙인 커밋이면
# 그 앱의 .env 가 서버에 아직 없다. 없는 채로 deploy 하면 컨테이너가
# 곧바로 죽는데 화면에는 「실행 실패」만 뜬다. setup 은 있으면 건드리지 않는다.
say "  setup.sh"
./setup.sh >>"$LOG" 2>&1 || say "  △ setup.sh 가 0 이 아닌 값을 냈습니다 (계속 진행)"

say "  deploy.sh"
if ./deploy.sh --no-pull >>"$LOG" 2>&1; then
  DEPLOY_OK=1
else
  DEPLOY_OK=0
  say "  ✗ deploy.sh 실패"
fi

# ── 진짜로 살아 있나 ───────────────────────────────────────
# 컨테이너가 떴다는 것과 사이트가 응답한다는 것은 다른 이야기다.
PUB="$(sed -n 's/^PROXY_PUBLISH=//p' proxy/.env 2>/dev/null | head -1)"
case "$PUB" in
  "" )          URL="http://localhost/health" ;;
  127.0.0.1:*)  URL="http://${PUB}/health" ;;
  *:*)          URL="http://localhost:${PUB##*:}/health" ;;
esac

HEALTHY=0
for i in $(seq 1 "$HEALTH_TRIES"); do
  if curl -fsS --max-time 3 "$URL" 2>/dev/null | grep -q '"ok"'; then HEALTHY=1; break; fi
  sleep 2
done

if [ "$DEPLOY_OK" = 1 ] && [ "$HEALTHY" = 1 ]; then
  say "  ✓ 배포 완료 · $URL 응답함"
  exit 0
fi

# ── 되돌리기 ──────────────────────────────────────────────
say "  ✗ 배포 후 상태가 나쁩니다 (deploy=$DEPLOY_OK health=$HEALTHY) → $OLD 로 되돌립니다"
git reset --hard --quiet "$OLD"
./setup.sh  >>"$LOG" 2>&1
./deploy.sh --no-pull >>"$LOG" 2>&1
for i in $(seq 1 "$HEALTH_TRIES"); do
  if curl -fsS --max-time 3 "$URL" 2>/dev/null | grep -q '"ok"'; then
    say "  ↩ 되돌렸고 사이트는 살아 있습니다. 방금 커밋을 고쳐서 다시 올리세요."
    exit 1
  fi
  sleep 2
done
say "  ✗✗ 되돌린 뒤에도 응답이 없습니다. 사람이 봐야 합니다."
say "     docker ps  /  docker logs demo-proxy --tail 50"
exit 2
