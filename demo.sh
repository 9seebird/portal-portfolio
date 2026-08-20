#!/usr/bin/env bash
# =====================================================================
# 체험판을 한 번에 띄운다.
#
#   ./demo.sh              80 포트로 바로 (혼자 보는 서버 · 노트북)
#   ./demo.sh --behind     앞에 nginx 를 두는 경우 (127.0.0.1:8081 로만)
#
# 하는 일은 네 가지다.
#   1. setup.sh 를 불러 .env 들을 만들고 앱끼리 쓰는 토큰을 맞춘다
#   2. 그 위에 **체험판 값**을 덮어쓴다 (DEMO_MODE=1 · 계정 · 한도)
#   3. 데이터가 비어 있으면 가짜 데이터를 채운다
#   4. deploy.sh 로 순서대로 띄운다
#
# 두 번째로 실행해도 안전하다. 이미 있는 값은 그대로 두고, 체험판 값만
# 다시 맞춘다. 데이터도 이미 있으면 건드리지 않는다.
#
# AI 키만은 사람이 넣어야 한다. 이 스크립트가 지어낼 수 있는 값이 아니다.
#   portal/.env 의 OPENAI_API_KEY
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")"

MODE="--local"
[ "${1:-}" = "--behind" ] && MODE="--server"

say()  { printf '%s\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '  \033[31m✗\033[0m %s\n' "$*"; exit 1; }

# 값을 **덮어쓴다.** setup.sh 의 setval 은 비어 있을 때만 채우는데,
# 체험판 값은 그러면 안 된다. 이미 뭔가 들어 있어도 체험판 기준으로
# 되돌려 놓아야 다음 사람이 보는 화면이 늘 같다.
put() {   # put <파일> <키> <값>
  local f="$1" k="$2" v="$3"
  [ -f "$f" ] || die "$f 가 없습니다. setup.sh 가 실패한 것 같습니다."
  if grep -q "^${k}=" "$f"; then
    # 값에 / 나 & 가 들어가도 깨지지 않게 구분자를 | 로 쓴다
    sed -i "s|^${k}=.*|${k}=${v}|" "$f"
  else
    printf '%s=%s\n' "$k" "$v" >> "$f"
  fi
}
cur() { sed -n "s/^$2=//p" "$1" 2>/dev/null | head -1; }

# ── 1. 평소 준비 ────────────────────────────────────────────
say ""
say "▸ 기본 준비 (setup.sh)"
./setup.sh "$MODE" >/dev/null
ok ".env · 토큰 맞춤"

# ── 2. 체험판 값 ────────────────────────────────────────────
say ""
say "▸ 체험판 설정"
put portal/.env DEMO_MODE 1
put portal/.env DEMO_USER_ID "${DEMO_USER_ID:-demo}"
put portal/.env DEMO_PASSWORD "${DEMO_PASSWORD:-demo1234}"
put portal/.env DEMO_CHAT_PER_IP_DAY "${DEMO_CHAT_PER_IP_DAY:-20}"
put portal/.env DEMO_TOKENS_PER_MONTH "${DEMO_TOKENS_PER_MONTH:-3000000}"
put portal/.env DEMO_DB ./data/demo.db
ok "DEMO_MODE=1 · 계정 $(cur portal/.env DEMO_USER_ID) · 챗 IP당 하루 $(cur portal/.env DEMO_CHAT_PER_IP_DAY)회"

# ★ 80 을 차지하지 않는다.
#   이걸 받아서 띄우는 사람의 PC 에는 이미 뭔가 80 을 쓰고 있을 가능성이 높다.
#   체험판이 남의 자리를 뺏으면 안 된다. 서버(--behind)는 앞의 nginx 가
#   80/443 을 맡으므로 여기서는 127.0.0.1 로만 연다.
if [ "$MODE" = "--local" ]; then
  put proxy/.env PROXY_PUBLISH "${DEMO_PORT:-8090}:80"
  ok "주소 http://localhost:${DEMO_PORT:-8090}/  (바꾸려면 DEMO_PORT=9000 ./demo.sh)"
fi

# 남이 올린 첨부를 볼 수 있는 계정 목록. 체험판에서는 **비워 둔다.**
# 방문자끼리 서로 올린 파일이 보이면 안 된다.
put portal/.env UPLOAD_VIEWERS ""
ok "첨부 열람 계정 없음 (방문자끼리 서로 안 보임)"

# ★ 개발 모드는 반드시 끈다.
#   포털 헤더가 없어도 테스트 계정으로 통과시키는 모드다. 앱 하나만 띄워
#   놓고 고칠 때 편하라고 있는 것인데, 체험판에서는 **인증을 통째로
#   건너뛰는 뒷문**이 된다. setup.sh 가 서버 모드에서만 끄므로
#   (--local 로 띄우는 경우까지) 여기서 한 번 더 확실히 한다.
for d in */; do
  d="${d%/}"
  [ -f "$d/.env" ] || continue
  grep -q "^DEV_MODE=" "$d/.env" && put "$d/.env" DEV_MODE false
done
ok "DEV_MODE=false (모든 앱)"

# 자산 앱은 자기 서명키를 따로 쓴다. 예시 파일에 「여기에-생성한-값」이
# 그대로 남아 있으면 뜨자마자 죽는다.
AENV=it-asset/backend/.env.deploy
if [ -f "$AENV" ] && grep -q '^SECRET_KEY=여기에' "$AENV"; then
  put "$AENV" SECRET_KEY "$(head -c 48 /dev/urandom | base64 | tr -d '\n=+/' | cut -c1-40)"
  ok "자산 앱 서명키 새로 만듦"
fi

# ── 3. AI 키 ────────────────────────────────────────────────
KEY="$(cur portal/.env OPENAI_API_KEY)"
if [ -z "$KEY" ] || [[ "$KEY" == 발급받은* ]]; then
  say ""
  warn "portal/.env 의 OPENAI_API_KEY 가 비어 있습니다."
  warn "챗을 뺀 나머지는 전부 돌아갑니다. 챗까지 보이려면 키를 넣고 다시 실행하세요."
fi

# ── 4. 가짜 데이터 ──────────────────────────────────────────
#
# 엑셀·PPT 를 만들어야 해서 openpyxl · python-pptx · Pillow 가 필요하다.
# 이 PC 에 있으면 그걸 쓰고, 없으면 컨테이너 안에서 돌린다.
# 「도커만 있으면 된다」를 지키려는 것이다 (윈도우에는 파이썬이 없는 쪽이 보통이다).
say ""
say "▸ 가짜 데이터"
if python3 -c "import openpyxl, pptx, PIL" 2>/dev/null; then
  python3 tools/make_demo_data.py
else
  ok "이 PC 에 파이썬 꾸러미가 없어 컨테이너로 만듭니다 (처음 한 번만 좀 걸립니다)"
  docker build -q -t portfolio-tools tools >/dev/null
  # 리눅스에서는 컨테이너가 root 로 파일을 만들면 나중에 내가 못 고친다.
  docker run --rm -u "$(id -u):$(id -g)" -v "$PWD:/w" -w /w \
    portfolio-tools python tools/make_demo_data.py
fi

# ── 5. 띄우기 ───────────────────────────────────────────────
#
# ★ 체험판에서 안 띄우는 앱.
#
# 폴더 이름이 곧 앱 이름이다. DEMO_SKIP="a b" 로 몇 개를 빼고 띄울 수 있다.
DEMO_SKIP="${DEMO_SKIP-}"

TARGETS=""
for d in */; do
  d="${d%/}"
  [ -f "$d/docker-compose.yml" ] || continue
  case " $DEMO_SKIP " in *" $d "*) continue ;; esac
  TARGETS="$TARGETS $d"
done
[ -n "$DEMO_SKIP" ] && ok "안 띄우는 앱: $DEMO_SKIP  (코드는 저장소에 있습니다)"

say ""
./deploy.sh --no-pull $TARGETS

# ── 6. 각 앱에 자료 넣기 ────────────────────────────────────
#
# ★ 왜 여기서, 왜 컨테이너 안에서 하는가.
#
#   앱의 표 구조와 검사 규칙은 그 앱만 안다. 밖에서 DB 에 직접 쓰면
#   「그 앱의 업로드로는 통과 못 할 자료」가 화면에 앉게 되고, 그러면
#   파서가 망가져도 데모는 멀쩡해 보인다. 각 앱이 자기 파서를 거쳐
#   받아들이게 두면, 자료가 보인다는 것 자체가 그 앱이 돈다는 확인이 된다.
#
#   그래서 컨테이너가 뜬 **뒤에** 부른다. 이미 자료가 있으면
#   각 스크립트가 알아서 아무 일도 하지 않는다.
say ""
say "▸ 앱에 자료 넣기"

# ★ `docker compose exec` 가 아니라 `docker exec` 를 쓴다.
#
#   compose 는 「이 폴더의 이 서비스」로 컨테이너를 찾는다. 그런데 받는
#   사람이 같은 이름의 폴더로 다른 것을 이미 띄워 두었으면, compose 가
#   **남의 컨테이너를 이 프로젝트 것으로 보고** 그 안에서 명령을 돌린다.
#   실제로 그 일이 났다 — 체험판 자료를 넣는 명령이 남의 앱 안에서 실행됐다.
#   (파일이 없어서 실패로 끝났지만, 있었으면 남의 데이터가 덮였을 것이다)
#
#   docker exec 는 **컨테이너 이름 하나만** 본다. demo- 로 시작하는 이름은
#   이 저장소만 쓰므로, 헷갈릴 여지가 없다.
up() { docker ps --format '{{.Names}}' | grep -qx "$1"; }

seed() {   # seed <컨테이너> <설명> <명령...>
  local c="$1" label="$2"; shift 2
  if ! up "$c"; then warn "$c 가 떠 있지 않습니다 — $label 건너뜀"; return 0; fi
  say "  $label"
  docker exec -i "$c" "$@" 2>&1 | sed 's/^/  /' || warn "$label 자료를 넣지 못했습니다"
}

seed demo-asset-api     "자산관리"      python scripts/seed_demo.py
seed demo-leave-anomaly "연차 이상패턴"  python -m app.seed_demo
seed demo-manual-import "매뉴얼"        python -m app.seed_demo
seed demo-edu           "온라인 교육"    python -m app.seed_demo

# ── 6-1. 안 띄운 앱은 목록에서도 뺀다 ──────────────────────
#
# 앱은 뜰 때 포털에 자기를 등록하고, 그 기록은 portal/data 에 **남는다**.
# 한 번 등록되고 나면 다음에 그 앱을 안 띄워도 목록에는 그대로 있어서,
# 눌러 보면 502 가 난다 — 「있는 줄 알고 눌렀는데 없다」가 되는 것이다.
for s in $DEMO_SKIP; do
  py="import os,sqlite3
c = sqlite3.connect(os.environ.get('PORTAL_DB', './data/portal.db'))
c.execute('DELETE FROM services WHERE id=?', ('$s',))
c.commit()"
  if docker exec -i demo-portal python -c "$py" >/dev/null 2>&1; then
    ok "앱 목록에서도 뺐습니다: $s"
  else
    warn "$s 를 앱 목록에서 빼지 못했습니다 (포털이 안 떠 있을 수 있습니다)"
  fi
done

# 포털은 뜰 때 스스로 넣는다 (app/demo.py 의 seed_people).
# 앱들이 등록한 서비스를 켜는 것도 포털이 한다 — 앱이 언제 등록할지
# 밖에서는 알 수 없어서, 포털이 한동안 지켜보다가 켠다.
# ── 7. 진짜로 막혀 있는지 ──────────────────────────────────
# 설정 파일을 읽는 것이 아니라 **바깥에서 요청을 보내** 확인한다.
# 「고쳤다고 생각했는데 안 고쳐진 것」은 이 방법으로만 잡힌다.
say ""
say "▸ 안전장치 확인"
sleep 4
# ★ 도커 네트워크 안에서 프록시를 이름으로 부른다.
#   호스트에서 localhost 로 부르면 --behind 로 띄웠을 때 주소가 달라지고,
#   윈도우에서는 파이썬이 없을 수도 있다. 이 방법은 어디서나 같다.
docker run --rm --network demo-net -v "$PWD/tools:/t" \
  python:3.12-slim python /t/check_demo.py http://demo-proxy 2>&1 | tail -10 || \
  warn "확인에서 실패한 항목이 있습니다. 위 목록을 보세요."

say ""
say "──────────────────────────────────────────────"
say "  아이디  $(cur portal/.env DEMO_USER_ID)"
say "  비밀번호 $(cur portal/.env DEMO_PASSWORD)"
say ""
if [ "$MODE" = "--local" ]; then
  say "  http://localhost:${DEMO_PORT:-8090}/"
else
  say "  앞의 nginx 를 127.0.0.1:8081 로 넘기도록 설정하세요."
fi
say ""
