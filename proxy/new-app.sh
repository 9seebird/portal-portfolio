#!/usr/bin/env bash
# =====================================================================
# 새 앱을 프록시에 붙인다.  apps/서비스ID.conf 를 만들어 준다.
#
#   ./new-app.sh meeting-room
#   ./new-app.sh meeting-room meetingroom
#   ./new-app.sh it-asset asset-web 80
#
#   1번째 인자  서비스 ID      (영문 소문자·숫자·하이픈)
#   2번째 인자  컨테이너 이름   (생략하면 서비스 ID 에서 하이픈을 뺀 것)
#   3번째 인자  안쪽 포트       (생략하면 8080)
#
# 포트는 컨테이너 **안쪽** 포트다. 표준 규칙 v2 로 만든 앱은 8080 이라
# 안 줘도 되지만, nginx 로 화면을 주는 앱은 80 인 경우가 많다.
# 이 값이 틀리면 화면에 502 Bad Gateway 가 뜬다.
#
# 윈도우의 new-app.ps1 과 같은 일을 한다.
# =====================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ID="${1:-}"
CONTAINER="${2:-}"
PORT="${3:-8080}"

if [ -z "$ID" ]; then
  echo "사용법: ./new-app.sh <서비스ID> [컨테이너이름] [안쪽포트]"
  exit 1
fi

# 서비스 ID 규칙: 주소와 컨테이너 이름에 그대로 쓰인다.
if ! printf '%s' "$ID" | grep -Eq '^[a-z0-9]([a-z0-9-]*[a-z0-9])?$'; then
  echo "✗ 서비스 ID 는 영문 소문자·숫자·하이픈만 쓸 수 있습니다. (예: meeting-room)"
  exit 1
fi

[ -z "$CONTAINER" ] && CONTAINER="${ID//-/}"
# nginx 변수 이름에는 하이픈을 쓸 수 없다. meeting-room → meeting_room
VAR="${ID//-/_}"

TEMPLATE="$HERE/apps/_TEMPLATE.conf.txt"
TARGET="$HERE/apps/$ID.conf"

[ -f "$TEMPLATE" ] || { echo "✗ 본보기 파일이 없습니다: $TEMPLATE"; exit 1; }

if [ -f "$TARGET" ] && [ "${FORCE:-0}" != "1" ]; then
  echo "이미 있습니다: apps/$ID.conf"
  echo "덮어쓰려면:  FORCE=1 ./new-app.sh $ID $CONTAINER $PORT"
  exit 1
fi

{
  cat <<EOF
# ── $ID ──────────────────────────────────────────────────────
#   서비스 ID   : $ID      (포털 관리자 화면의 ID 와 같아야 한다)
#   컨테이너    : $CONTAINER
#   접속 주소   : /$ID/
#   안쪽 포트   : $PORT
#   만든 날짜   : $(date +%Y-%m-%d)
#
# portal.conf 의 server 블록 안으로 include 된다.
# ─────────────────────────────────────────────────────────────

EOF
  # 본보기의 안내 머리말은 빼고 설정만 가져온다
  sed -n '/^# 직원이 주소창에/,$p' "$TEMPLATE" \
    | sed -e "s/__PORT__/$PORT/g" \
          -e "s/__CONTAINER__/$CONTAINER/g" \
          -e "s/__VAR__/$VAR/g" \
          -e "s/__ID__/$ID/g"
} > "$TARGET"

echo "만들었습니다: apps/$ID.conf"
echo ""
echo "다음 순서:"
echo "  1. $CONTAINER 컨테이너가 demo-net 에 떠 있는지 확인 (안쪽 포트 $PORT)"
echo "  2. ./deploy.sh proxy"
echo "  3. 포털 관리자 화면 → 서비스 관리 → $ID → 접근 범위·담당자 정하고 켜기"
echo "  4. http://<서버>/$ID/ 로 접속 확인"
