#!/usr/bin/env bash
# =====================================================================
# 받은 앱을 켜도 되는지 본다. **아무것도 바꾸지 않는다.**
#
#   ./check-intake.sh leave-anomaly          이미 푼 폴더
#   ./check-intake.sh ~/받은것/meeting-room  아무 경로나
#
# 다른 부서 사람이 웍스AI 로 만든 zip 을 받았을 때, 풀고 나서 **켜기 전에**
# 한 번 돌린다. 윈도우의 check-intake.ps1 과 같은 일을 한다.
#
# ── 이 도구가 보는 것 / 못 보는 것 ──────────────────────────
# 기계가 볼 수 있는 것만 본다. 파일이 있나, 설정이 규칙대로인가, 위험한
# 글자가 박혀 있나. **숫자가 맞는지는 못 본다.** 그건 사람이 봐야 한다.
# 맨 끝에 사람이 볼 목록을 같이 찍어 준다.
#
# ✗ 가 하나라도 있으면 켜지 않는다. △ 는 켜되 만든 사람에게 알린다.
# =====================================================================
set -uo pipefail

DIR="${1:-}"
if [ -z "$DIR" ] || [ ! -d "$DIR" ]; then
  echo "쓰는 법:  ./check-intake.sh <앱 폴더>"
  echo "예:       ./check-intake.sh leave-anomaly"
  exit 1
fi
DIR="$(cd "$DIR" && pwd)"
NAME="$(basename "$DIR")"

OK=0; WARN=0; BAD=0
ok()   { echo "  ✓ $1"; OK=$((OK+1)); }
warn() { echo "  △ $1"; WARN=$((WARN+1)); }
bad()  { echo "  ✗ $1"; BAD=$((BAD+1)); }
line() { echo ""; echo "── $1 ──"; }

# 코드·설정만 훑는다 (data, 가상환경, 캐시는 뺀다)
# 남이 만든 라이브러리는 우리가 볼 것이 아니다. 최소화된 파일(xlsx.min.js 같은)은
# 한 줄이 수만 자라, 걸리면 화면을 통째로 덮어 버린다. 크기로도 한 번 거른다.
findsrc() {
  find "$DIR" -type f -size -200k \
    ! -path "*/data/*" ! -path "*/.git/*" ! -path "*/__pycache__/*" \
    ! -path "*/node_modules/*" ! -path "*/.venv/*" ! -path "*/venv/*" \
    ! -path "*/vendor/*" ! -path "*/lib/*" ! -path "*/libs/*" \
    ! -name "*.min.js" ! -name "*.min.css" ! -name "*.bundle.js" "$@"
}
# 긴 줄은 잘라서 보여 준다. 원본을 다 찍으면 무엇이 문제인지 오히려 안 보인다.
cut140() { sed "s|^${DIR}/|      |" | cut -c1-140; }
grepsrc() { findsrc -name "$2" -print0 2>/dev/null | xargs -0 grep -l "$1" 2>/dev/null | head -5; }
has()     { [ -n "$(grepsrc "$1" "$2")" ]; }

# 이 스크립트가 있는 곳(= portal-service 뿌리)의 포털 .env. 없으면 빈 값이 된다.
HERE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERE_PORTAL_ENV="$HERE_ROOT/portal/.env"

COMPOSE="$DIR/docker-compose.yml"
DOCKERFILE="$DIR/Dockerfile"

# 앱 모양을 먼저 본다. 셋 중 하나다.
#
#   python   .py 가 있다                     (대부분)
#   node     package.json 에 start 가 있다   (Hireflow 처럼 받은 앱)
#   static   둘 다 없다 — nginx 하나가 파일만 준다 (it-guide)
#
# ★ 전에는 「.py 가 없으면 정적 앱」이었다. 그래서 Node 로 만든 앱을
#   정적 앱으로 보고, **X-User-Id 를 읽는지 · DEV_MODE 를 다루는지 검사를
#   통째로 건너뛰었다.** 로그인을 스스로 만든 Node 앱이 들어와도
#   ✓ 만 찍혔을 것이다. 서버가 있으면 언어와 무관하게 검사해야 한다.
PYFILES=$(findsrc -name '*.py' 2>/dev/null | head -1)
PKGJSON=$(findsrc -name 'package.json' 2>/dev/null | head -1)
if   [ -n "$PYFILES" ]; then
  KIND=python; SRC_LABEL="소스코드(.py)"
elif [ -n "$PKGJSON" ] && grep -q '"start"' "$PKGJSON" 2>/dev/null; then
  KIND=node;   SRC_LABEL="소스코드(.js/.mjs)"
else
  KIND=static; SRC_LABEL=""
fi
# 뒤쪽 검사들이 아직 이 값을 본다. 「서버가 없는 앱」이라는 뜻이다.
[ "$KIND" = "static" ] && STATIC_ONLY=1 || STATIC_ONLY=0

# 그 앱의 소스에서 글자를 찾는다. 언어마다 확장자가 다르므로 여기서 가른다.
hassrc() {   # hassrc <찾을 글자>
  case "$KIND" in
    python) findsrc -name '*.py' -print0 2>/dev/null ;;
    node)   findsrc \( -name '*.js' -o -name '*.mjs' -o -name '*.ts' \) -print0 2>/dev/null ;;
    *)      return 1 ;;
  esac | xargs -0 grep -l "$1" 2>/dev/null | head -1 | grep -q .
}
grep -qE '^\s*build:' "$COMPOSE" 2>/dev/null && NEEDS_DOCKERFILE=1 || NEEDS_DOCKERFILE=0

# 파이썬만 보면 정적 앱을 놓친다. 설정 파일까지 같이 훑는다.
anysrc() {
  findsrc \( -name '*.py' -o -name '*.yml' -o -name '*.yaml' -o -name '*.sh' \
             -o -name '*.conf' -o -name '*.js' \) -print0 2>/dev/null \
    | xargs -0 grep -l "$1" 2>/dev/null | head -1
}

echo "====================================================="
echo " 받은 앱 점검 : $NAME"
echo " 회사 표준 규칙 v2 기준 · 이 도구는 아무것도 바꾸지 않습니다"
echo "====================================================="

# ── 1. 제출물 (규칙 16) ──────────────────────────────────────
line "제출물이 다 왔나 (규칙 16)"
# 앱이 backend/ frontend/ 로 나뉘어 있으면 뿌리에 없다. 폴더 안 어디서든 찾는다.
NEED="docker-compose.yml .env.example .gitignore README.md"
[ "$KIND" = "python" ]        && NEED="requirements.txt $NEED"
[ "$KIND" = "node" ]          && NEED="package.json $NEED"
[ "$NEEDS_DOCKERFILE" -eq 1 ] && NEED="Dockerfile $NEED"
[ "$KIND" = "node" ]          && echo "  · package.json 에 start 가 있습니다 — Node 서버 앱으로 봅니다 (Hireflow 같은 모양)"
[ "$KIND" = "static" ]        && echo "  · 서버 소스가 없습니다 — 정적 파일만 주는 앱으로 봅니다 (it-guide 같은 모양)"
[ "$NEEDS_DOCKERFILE" -eq 0 ] && echo "  · compose 에 build 가 없습니다 — 이미지를 그대로 쓰는 앱으로 봅니다"
for f in $NEED; do
  HIT=$(findsrc -name "$f" 2>/dev/null | head -1)
  if [ -n "$HIT" ]; then
    REL="${HIT#$DIR/}"
    [ "$REL" = "$f" ] && ok "$f" || ok "$f  ($REL)"
  else
    bad "$f 가 없습니다"
  fi
done
[ -n "$SRC_LABEL" ] && ok "$SRC_LABEL"

# ── 2. 못 넘는 선 ────────────────────────────────────────────
line "못 넘는 선 — 하나라도 걸리면 켜지 않는다"

# .env 가 있다고 무조건 사고는 아니다. setup 을 이미 돌린 폴더에는 당연히 있다.
# 둘을 가르는 건 **토큰이 우리 것인가**다. 포털 것과 같으면 여기서 만들어진 것이고,
# 다르면 바깥에서 딸려 온 것 — 남의 비밀번호가 그대로 넘어왔다는 뜻이다.
if [ -f "$DIR/.env" ]; then
  MINE=$(grep -m1 '^AUDIT_TOKEN=' "$HERE_PORTAL_ENV" 2>/dev/null | cut -d= -f2-)
  THEIRS=$(grep -m1 '^AUDIT_TOKEN=' "$DIR/.env" 2>/dev/null | cut -d= -f2-)
  if [ -n "$MINE" ] && [ "$MINE" = "$THEIRS" ]; then
    warn ".env 가 있습니다 — setup 이 만든 것으로 보입니다 (토큰이 포털 것과 같음)"
    echo "      → 압축을 **푼 직후**에 돌리셨다면 이건 사고입니다. 다시 보세요."
  else
    bad ".env 가 딸려 왔습니다. 만든 분의 비밀번호·토큰이 그대로 넘어온 것입니다."
    echo "      → 만든 분에게 알리고, 그 값들은 **못 쓰는 것**으로 봐야 합니다."
    echo "      → 이 폴더의 .env 는 지우고 setup 으로 새로 만드세요."
  fi
else
  ok ".env 가 들어 있지 않습니다"
fi

if grep -qE '^\s*ports:' "$COMPOSE" 2>/dev/null; then
  bad "docker-compose.yml 에 ports 가 있습니다 (규칙 14 — 바깥 포트 금지)"
  echo "      → 앱마다 8080 을 열면 두 번째 앱부터 충돌합니다."
else
  ok "바깥 포트를 열지 않습니다"
fi

SECRET=$(findsrc \( -name '*.py' -o -name '*.js' -o -name '*.html' \) -print0 2>/dev/null \
  | xargs -0 grep -nHEi "(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*[\"'][^\"']{8,}[\"']" 2>/dev/null \
  | grep -viE "getenv|environ|os\.env|process\.env|example|여기에|입력|placeholder|\.\.\.|xxx|change[-_]?me|your[-_]|dummy|sample|todo|insecure|바꾸" | head -5)
if [ -n "$SECRET" ]; then
  bad "코드에 비밀번호·토큰처럼 보이는 글자가 박혀 있습니다 (규칙 13)"
  echo "$SECRET" | cut140
else
  ok "코드에 박힌 비밀번호·토큰이 안 보입니다"
fi

# ── 3. 도커 (규칙 14) ────────────────────────────────────────
line "도커 설정 (규칙 14)"
# 진짜 위험한 건 **떠다니는 태그**다. latest 나 태그 없음은 어제와 오늘이 다른 이미지가
# 된다. 정적 파일만 주는 앱은 nginx 를 쓸 수도 있으니, python 만 고집하지 않는다.
DFS=$(findsrc -name 'Dockerfile' 2>/dev/null)
if [ -z "$DFS" ]; then
  [ "$NEEDS_DOCKERFILE" -eq 1 ] && bad "compose 에 build 가 있는데 Dockerfile 이 없습니다" \
                                || ok "Dockerfile 없이 이미지를 그대로 씁니다"
else
  while IFS= read -r df; do
    [ -z "$df" ] && continue
    FROMLINE=$(grep -iE '^\s*FROM ' "$df" | head -1)
    IMG=$(echo "$FROMLINE" | awk '{print $2}')
    WHERE="${df#$DIR/}"
    case "$IMG" in
      python:3.13-slim)  ok "$WHERE — $IMG (규칙 14 그대로)" ;;
      *:latest|"")       bad "$WHERE — 떠다니는 태그입니다 (${FROMLINE:-FROM 줄 없음}). 어제와 오늘이 다른 이미지가 됩니다" ;;
      python:*)          warn "$WHERE — $IMG. 고정은 됐지만 규칙 14 는 python:3.13-slim 입니다" ;;
      *:*)               ok  "$WHERE — $IMG (태그가 고정돼 있습니다)" ;;
      *)                 bad "$WHERE — 태그가 없습니다 ($FROMLINE). 어제와 오늘이 다른 이미지가 됩니다" ;;
    esac
  done <<< "$DFS"
fi
grep -qE '^\s*expose:'         "$COMPOSE" 2>/dev/null && ok "expose 를 씁니다"          || warn "expose 가 없습니다"
grep -q  'demo-net'          "$COMPOSE" 2>/dev/null && ok "demo-net 에 붙습니다"     || bad  "demo-net 설정이 없습니다 (포털이 앱을 못 찾습니다)"
grep -qE 'external:\s*true'    "$COMPOSE" 2>/dev/null && ok "demo-net 이 external 입니다" || bad "networks 에 external: true 가 없습니다"
grep -qE '^\s*container_name:' "$COMPOSE" 2>/dev/null && ok "container_name 이 있습니다" || bad "container_name 이 없습니다"
# 붙는 자리는 앱마다 다르다 (./data:/data · ./data:/app/data …).
# 중요한 건 **바깥 ./data 폴더가 붙어 있느냐**지, 컨테이너 안 경로가 아니다.
grep -qE '^\s*-\s*\./data:' "$COMPOSE" 2>/dev/null && ok "./data 폴더가 붙어 있습니다"   || warn "./data 가 붙어 있지 않습니다 (저장하는 앱이면 껐다 켜면 사라집니다)"

# ── 4. 로그인·권한 (규칙 7~10) ───────────────────────────────
line "로그인과 권한 (규칙 7~10)"
if [ "$KIND" = "static" ]; then
  ok "정적 파일 앱이라 헤더를 읽지 않습니다 — 권한은 앞단 프록시가 막습니다"
else
  # ★ 「헤더를 안 읽는다」가 곧 사고는 아니다. 스스로 로그인을 만들었으면
  #   사고고, 사용자를 알 필요가 없는 앱이면 그냥 안 읽는 것이다.
  #   그래서 ✗ 가 아니라 △ 로 두고, 아래 로그인 화면 검사와 같이 본다.
  if hassrc "[Xx]-[Uu]ser-[Ii]d"; then
    ok "포털 헤더(X-User-Id)를 읽습니다"
  else
    warn "포털 헤더를 읽는 곳이 안 보입니다 — 사용자를 알아야 하는 앱이면 규칙 10 위반입니다"
  fi
  hassrc "DEV_MODE" && ok "DEV_MODE 를 다룹니다" || warn "DEV_MODE 처리가 안 보입니다 (규칙 8)"
fi
VIEWER=$(findsrc \( -name '*.py' -o -name '*.js' \) -print0 2>/dev/null | xargs -0 grep -nHw "viewer" 2>/dev/null | head -3)
[ -z "$VIEWER" ] && ok "viewer 권한이 남아 있지 않습니다" || { warn "viewer 가 남아 있습니다 (규칙 9 — user/admin 둘뿐)"; echo "$VIEWER" | cut140; }
if grep -rq "login\|signup\|회원가입" --include=*.html "$DIR" 2>/dev/null; then
  warn "화면에 로그인·회원가입처럼 보이는 것이 있습니다 (규칙 7 — 만들지 않습니다)"
else
  ok "로그인 화면을 따로 만들지 않았습니다"
fi

# ── 5. 포털에 붙이기 (규칙 22~24) ────────────────────────────
line "포털 연결 (규칙 22~24)"
# 등록은 앱 코드가 아니라 compose 의 작은 컨테이너가 할 수도 있다 (it-guide 방식).
[ -n "$(anysrc 'api/services/register')" ] && ok "뜰 때 포털에 자기를 등록합니다" \
  || bad "포털 자동 등록이 없습니다 (관리자 화면에 안 뜹니다)"
[ -n "$(anysrc 'api/audit')" ]  && ok "포털 이력으로 보냅니다" || warn "포털 이력 전송이 없습니다 (규칙 23)"
[ -n "$(anysrc 'health')" ]     && ok "살아 있는지 확인하는 주소가 있습니다" || warn "api/health 가 없습니다 (규칙 4)"
KEYS="PORTAL_API_URL AUDIT_TOKEN"
[ "$KIND" != "static" ] && KEYS="DEV_MODE $KEYS"
for k in $KEYS; do
  grep -q "^$k=" "$DIR/.env.example" 2>/dev/null && ok ".env.example 에 $k 가 있습니다" \
    || warn ".env.example 에 $k 가 없습니다 (규칙 13)"
done

# ── 6. 주소 (규칙 3·24) ──────────────────────────────────────
line "화면이 부르는 주소 (규칙 3·24)"
# /manual-import/api/me 처럼 **다른 앱**을 부르는 건 정상이다 (포털 아래 경로).
# 문제는 맨 위 /api/ 나 /static/ 이다 — 그건 포털 최상위를 찾아간다.
ABS=$(findsrc \( -name '*.html' -o -name '*.js' \) -print0 2>/dev/null \
  | xargs -0 grep -nHE "(fetch|axios\.[a-z]+|XMLHttpRequest[^;]*open)\s*\(\s*[\"'\`]/(api|static)/" 2>/dev/null | head -5)
[ -z "$ABS" ] && ok "API 주소가 상대경로입니다" || { bad "화면이 슬래시로 시작하는 주소로 API 를 부릅니다 (포털 최상위를 찾아가 404)"; echo "$ABS" | cut140; }

CDN=$(findsrc -name '*.html' -print0 2>/dev/null \
  | xargs -0 grep -nHE "(src|href)=[\"']https?://" 2>/dev/null | head -5)
[ -z "$CDN" ] && ok "바깥 인터넷에서 받아오는 파일이 없습니다" \
  || { warn "화면이 바깥 인터넷 주소를 부릅니다 — 사내망에서 막히면 화면만 뜨고 안 돕니다"; echo "$CDN" | cut140; }

# ── 7. 잔가지 ────────────────────────────────────────────────
line "그 밖에"
if [ -f "$DIR/requirements.txt" ]; then
  LOOSE=$(grep -vE '^\s*(#|$)' "$DIR/requirements.txt" | grep -vE '==' | head -5)
  [ -z "$LOOSE" ] && ok "requirements.txt 버전이 고정돼 있습니다" \
    || { warn "버전이 안 붙은 것이 있습니다 (규칙 15) — 나중에 저절로 바뀝니다"; echo "$LOOSE" | sed 's|^|      |'; }
fi
if [ -f "$DIR/.gitignore" ]; then
  grep -q "^\.env" "$DIR/.gitignore" && ok ".gitignore 에 .env 가 있습니다" || bad ".gitignore 에 .env 가 없습니다"
  grep -q "^data" "$DIR/.gitignore"  && ok ".gitignore 에 data/ 가 있습니다" || warn ".gitignore 에 data/ 가 없습니다"
fi
# grep -c 는 파일이 하나뿐이면 "개수" 만 찍는다 (파일이름:개수 가 아니다).
# -H 를 붙여야 항상 같은 모양이 나온다. 안 붙이면 한 파일짜리 앱에서 0 으로 샌다.
# ★ 파이썬 전용 검사다. Node 앱에 대고 세면 늘 0 이라 헛경고가 난다.
if [ "$KIND" = "python" ]; then
DOC=$(findsrc -name '*.py' -print0 2>/dev/null | xargs -0 grep -cH '"""' 2>/dev/null | awk -F: '{s+=$NF} END{print s+0}')
[ "${DOC:-0}" -ge 4 ] && ok "API 설명(docstring)이 붙어 있습니다 (규칙 17)" \
  || warn "설명이 거의 없습니다 (규칙 17) — 챗 도구를 만들 근거가 됩니다"
fi

# ── 마무리 ───────────────────────────────────────────────────
echo ""
echo "====================================================="
echo " 기계가 본 결과 :  ✓ $OK    △ $WARN    ✗ $BAD"
if [ "$BAD" -gt 0 ]; then
  echo " ▶ ✗ 가 있습니다. **켜지 마세요.** 만든 분에게 돌려보내세요."
elif [ "$WARN" -gt 0 ]; then
  echo " ▶ 켜도 됩니다. △ 는 만든 분에게 알려 두세요."
else
  echo " ▶ 기계가 보는 것은 다 통과했습니다."
fi
echo "====================================================="

cat <<'EOF'

── 여기서부터는 사람이 봐야 합니다 (15분) ──

  1. 숫자를 만드는 앱인가?
     → 그렇다면 **원본과 대조할 표본**을 만든 분에게 받으세요.
       "이 파일 넣으면 이 숫자가 나온다" 를 직접 맞춰 보기 전에는 켜지 마세요.
       에러는 티가 나지만, 틀린 숫자는 조용합니다.

  2. 제일 큰 실제 파일로 돌려봤나?
     → 5MB 로 시험하고 63MB 에서 멈추는 일이 실제로 있었습니다.

  3. 지우기·되돌리기가 있나?
     → 없으면 잘못 넣은 것이 영영 남습니다.

  4. 남기는 것이 개인정보·재무자료인가?
     → 보관 기간과 **지울 사람**을 정하기 전에는 켜지 마세요.

  5. 담당자(admin)가 누구인가?
     → 만든 사람과 다를 수 있습니다. 정해지지 않으면 켜지 않습니다.

  자세한 절차 : docs/앱_입고_점검.md
EOF
[ "$BAD" -gt 0 ] && exit 1 || exit 0
