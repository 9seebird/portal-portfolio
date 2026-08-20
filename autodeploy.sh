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
# ★ 다시 시작(exec)한 경우에는 이미 9번을 쥐고 있다. 다시 잠그려 하면 안 된다.
if [ -z "${AUTODEPLOY_REEXEC:-}" ]; then
  exec 9>"$LOCK"
  flock -n 9 || { echo "$(date '+%F %T')  (앞 배포가 아직 돕니다 — 건너뜀)" >>"$LOG"; exit 0; }
fi

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
#
# 여기서 밀어 버리면 급하게 손본 것이 소리 없이 사라진다. 되돌릴 때
# git reset --hard 를 쓰기 때문에 진짜로 사라진다.
#
# ★ 단, **추적되는 파일이 바뀐 경우만** 본다 (--untracked-files=no).
#
#   처음에는 추적 안 되는 파일(??)까지 중단 사유로 봤다. 그랬더니 서버에
#   a.out 하나가 굴러다니는 것만으로 자동 배포가 영영 멈췄다. 그런 파일은
#   git pull 로도 reset --hard 로도 사라지지 않으니 잃을 것이 없는데,
#   고치려면 매번 SSH 로 들어가야 해서 자동화한 뜻이 없어진다.
#   알려는 주되 막지는 않는다.
DIRTY="$(git status --porcelain --untracked-files=no)"
if [ -n "$DIRTY" ]; then
  say "✗ 서버에서 고친 파일이 있어 멈춥니다 (덮어쓰면 사라집니다):"
  printf '%s\n' "$DIRTY" | sed 's/^/          /' | tee -a "$LOG"
  say "  (버릴 것이면  git checkout -- <파일>  후 다시)"
  exit 1
fi

JUNK="$(git status --porcelain --untracked-files=normal | grep '^??' || true)"
if [ -n "$JUNK" ]; then
  say "  △ 저장소에 없는 파일이 있습니다 (배포는 그대로 진행):"
  printf '%s\n' "$JUNK" | sed 's/^/          /' | tee -a "$LOG"
fi

# ── 새 커밋이 있나 ─────────────────────────────────────────
git fetch --quiet origin || { say "✗ git fetch 실패 (네트워크·열쇠 확인)"; exit 1; }
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
# 되돌릴 자리. 다시 시작한 경우에는 이미 받은 뒤라 HEAD 가 새 커밋이므로,
# 처음 실행이 넘겨준 값을 그대로 쓴다.
OLD="${AUTODEPLOY_OLD:-$(git rev-parse HEAD)}"
NEW="$(git rev-parse "origin/$BRANCH")"

# 자기 자신이 바뀌는지 보려고 미리 재 둔다.
SELF_BEFORE="$(sha1sum "$0" 2>/dev/null | cut -d" " -f1)"

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

# ★ 자기 자신이 바뀌었으면 **새 것으로 다시 시작한다.**
#
#   이 스크립트는 도는 도중에 git pull 로 자기 파일을 갈아 끼운다. 그런데
#   bash 는 이미 읽은 부분을 그대로 이어서 실행하므로, 아래의 배포·헬스체크·
#   되돌리기는 **옛 로직**이 돈다.
#
#   그게 한 번은 이렇게 나타났다. 헬스체크 주소 계산 오류를 고쳐 올렸는데,
#     · 받기는 새 것을 받고
#     · 돌기는 옛 로직으로 돌아 health=0 이 되고
#     · 되돌리기(reset --hard)가 그 수정을 도로 지웠다
#   그래서 몇 번을 올려도 같은 자리에서 실패했다 — 고칠 수가 없는 구조였다.
#
#   exec 로 갈아타면 그 지점부터는 온전히 새 스크립트다.
#   AUTODEPLOY_REEXEC 는 다시 시작이 한 번만 일어나게 하는 표식이다.
SELF_AFTER="$(sha1sum "$0" 2>/dev/null | cut -d" " -f1)"
if [ -n "$SELF_BEFORE" ] && [ "$SELF_BEFORE" != "$SELF_AFTER" ] \
   && [ -z "${AUTODEPLOY_REEXEC:-}" ]; then
  say "  autodeploy.sh 자신이 바뀌었습니다 — 새 것으로 다시 시작합니다"
  export AUTODEPLOY_REEXEC=1 AUTODEPLOY_OLD="$OLD"
  exec bash "$0" "$@"
fi

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
# ★ PROXY_PUBLISH 에서 **호스트 포트**를 뽑는다.
#
#   값의 모양이 두 가지다.
#       127.0.0.1:8081:80   (앞에 nginx 를 두는 서버)
#       8090:80             (혼자 쓰는 로컬)
#   맨 뒤 토막은 **컨테이너 안쪽 포트(80)** 라서 밖에서 두드릴 수 없다.
#   필요한 것은 뒤에서 두 번째다.
#
#   예전에는 ${PUB##*:} 로 맨 뒤를 집었다. 그래서 주소가
#       http://127.0.0.1:8081:80/health   (포트가 두 개)
#       http://localhost:80/health        (컨테이너 포트)
#   처럼 나왔고, curl 이 늘 실패해 health=0 이 되었다. 배포는 멀쩡한데
#   「상태가 나쁘다」며 되돌리고, 되돌린 뒤에도 같은 이유로 실패해서
#   「사람이 봐야 합니다」로 끝났다 — 검사 자체가 틀렸던 것이다.
PUB="$(sed -n 's/^PROXY_PUBLISH=//p' proxy/.env 2>/dev/null | head -1 | tr -d '\r' | tr -d '"')"
if [ -z "$PUB" ]; then
  HOSTPORT="127.0.0.1:80"
else
  HOSTPORT="${PUB%:*}"                  # 뒤의 컨테이너 포트를 뗀다
  case "$HOSTPORT" in
    0.0.0.0:*)  HOSTPORT="127.0.0.1:${HOSTPORT##*:}" ;;   # 0.0.0.0 으로는 두드리지 않는다
    *:*)        ;;                                        # 이미 주소:포트
    *)          HOSTPORT="127.0.0.1:$HOSTPORT" ;;         # 포트만 있던 경우
  esac
fi
URL="http://$HOSTPORT/health"

# 어디를 두드리는지 남긴다. 안 남기면 실패했을 때 「health=0」만 보이고
# 주소가 틀린 것인지 앱이 죽은 것인지 구분할 수가 없다 — 실제로 그랬다.
say "  살아있는지 확인 — $URL"
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
