#!/usr/bin/env bash
# =====================================================================
# 사내 정보가 저장소에 섞였는지 본다. **아무것도 고치지 않는다.**
#
#   ./tools/check_secrets.sh              전체
#   ./tools/check_secrets.sh --staged     커밋하려는 것만 (훅에서 쓸 때)
#
# 나가면 안 되는 것이 나가는 사고는 「몰라서」가 아니라 「눈에 안 띄어서」
# 난다. 이번에도 PPT 도형으로 가린 IP 가 이미지 추출에서 되살아났고,
# 테스트 픽스처에 실명이 남아 있었다. 사람이 매번 눈으로 볼 수는 없다.
#
# ── 실명·실제 대역을 여기 적지 않는 이유 ──────────────────────
# 이 파일은 공개 저장소에 들어간다. 「새면 안 되는 것」 목록을 여기 적으면
# 그 목록 자체가 새는 것이다. 그래서 회사 고유의 낱말은 밖에서 받는다.
#
#   로컬  : 저장소 뿌리에 .secretwords (한 줄에 하나, .gitignore 에 있음)
#   Actions: 저장소 Secrets 의 SECRET_WORDS 를 워크플로가 파일로 떨궈 준다
#
# 파일이 없으면 그 검사만 건너뛴다 (아래 「일반 검사」는 늘 돈다).
# =====================================================================
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --strict : 낱말 목록이 없으면 「건너뜀」이 아니라 「실패」로 본다.
#            pre-push 훅이 이 모드로 부른다 (.githooks/pre-push).
STRICT=0
for a in "$@"; do [ "$a" = "--strict" ] && STRICT=1; done
cd "$ROOT" || exit 1
BAD=0; WARN=0
bad() { echo "  ✗ $1"; BAD=$((BAD+1)); }
warn(){ echo "  △ $1"; WARN=$((WARN+1)); }
sec() { echo ""; echo "── $1 ──"; }

if [ "${1:-}" = "--staged" ]; then
  mapfile -t FILES < <(git diff --cached --name-only --diff-filter=ACM)
else
  # --others --exclude-standard 를 붙여야 아직 git add 하지 않은 파일도 본다.
  # 이게 없으면 새로 붙인 앱 폴더가 통째로 검사에서 빠진다 —
  # 정작 처음 올리는 코드가 제일 위험한데 그걸 안 보는 셈이었다.
  mapfile -t FILES < <(git ls-files --cached --others --exclude-standard)
fi
[ ${#FILES[@]} -eq 0 ] && { echo "볼 파일이 없습니다."; exit 0; }

# 텍스트 파일만 추린다 (이미지·DB 를 grep 하면 느리고 시끄럽다)
TEXT=(); for f in "${FILES[@]}"; do [ -f "$f" ] && grep -Iq . "$f" 2>/dev/null && TEXT+=("$f"); done

sec "나가면 안 되는 파일이 섞였나"
for f in "${FILES[@]}"; do
  case "$f" in
    *.env|*/.env|.env)                bad "$f — 환경설정 파일 (토큰·키가 들어 있습니다)" ;;
    *.pptx|*.ppt|*.doc|*.docx)        bad "$f — 원본 문서. 가림 처리 전 내용이 그대로 들어 있을 수 있습니다" ;;
    *.pem|*.key|*id_rsa*|*id_ed25519*) bad "$f — 열쇠 파일" ;;
    *.db|*.sqlite|*.sqlite3)          warn "$f — DB 파일. 실제 자료가 들어 있지 않은지 보세요" ;;
    *.xlsx|*.xls)
        case "$f" in
          */demo/*|*/example*|*예시*|*샘플*) : ;;   # 체험판용은 통과
          *) warn "$f — 엑셀. 체험판용이 맞는지 보세요" ;;
        esac ;;
  esac
done
[ "$BAD" = 0 ] && echo "  ✓ 없음"

sec "열쇠·토큰이 코드에 박혔나"
if [ ${#TEXT[@]} -gt 0 ]; then
  # 실제로 새면 큰일 나는 것들만. 흔한 오탐(예: 'password' 라는 낱말)은 넣지 않는다.
  PAT='BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9]{32,}|xox[baprs]-[A-Za-z0-9-]{10,}'
  if OUT=$(grep -InE "$PAT" "${TEXT[@]}" 2>/dev/null | grep -vE '\.example|check_secrets\.sh'); then
    echo "$OUT" | head -10 | sed 's/^/  ✗ /'; BAD=$((BAD+1))
  else echo "  ✓ 없음"; fi
fi

sec "회사 고유 낱말 (실명·실제 도메인·실제 대역)"
WORDS="${SECRET_WORDS_FILE:-$ROOT/.secretwords}"
if [ -s "$WORDS" ]; then
  # 빈 줄과 # 주석은 뺀다. 한 줄이라도 통째로 비면 모든 파일이 걸린다.
  TMP=$(mktemp); grep -vE '^\s*(#|$)' "$WORDS" | sed 's/[[:space:]]*$//' | grep -v '^$' > "$TMP"
  if [ -s "$TMP" ] && [ ${#TEXT[@]} -gt 0 ]; then
    if OUT=$(grep -Fnf "$TMP" "${TEXT[@]}" 2>/dev/null); then
      echo "$OUT" | head -20 | sed 's/^/  ✗ /'
      n=$(echo "$OUT" | wc -l); [ "$n" -gt 20 ] && echo "  … 그 외 $((n-20))건"
      BAD=$((BAD+1))
    else echo "  ✓ 없음 ($(wc -l < "$TMP")개 낱말로 검사)"; fi
  fi
  rm -f "$TMP"
elif [ "$STRICT" = 1 ]; then
  # ★ --strict 에서는 「건너뛰기」가 곧 구멍이다.
  #
  #   PC 가 두 대라 생기는 문제다. 회사 PC 에는 목록이 있고 집 PC 에는 없으면,
  #   집에서 push 할 때 이 검사만 조용히 빠진다. 그런데 검사가 빠졌다는 사실은
  #   화면을 눈여겨봐야 알 수 있고, push 는 그냥 성공한다.
  #   그래서 pre-push 훅은 --strict 로 부른다 — **없으면 막는다.**
  echo "  ✗ 낱말 목록이 없습니다 ($WORDS)"
  echo "    이 PC 에서는 실명 검사를 할 수 없어 push 를 막습니다."
  echo "    → 다른 PC 의 .secretwords 를 저장소 뿌리에 복사하세요."
  echo "      (깃에 올라가지 않는 파일이라 PC 마다 한 번씩 두어야 합니다)"
  BAD=$((BAD+1))
else
  warn "낱말 목록이 없어 이 검사는 건너뜁니다 ($WORDS)"
fi

sec "사설 IP (참고용 — 막지는 않습니다)"
if [ ${#TEXT[@]} -gt 0 ]; then
  ALLOW='10\.20\.(30|40|50)\.|10\.0\.0\.|10\.10\.100\.|127\.0\.0\.1|0\.0\.0\.0|192\.168\.(0|1)\.1$'
  grep -InoE '\b(10|192\.168|172\.(1[6-9]|2[0-9]|3[01]))\.[0-9]{1,3}\.[0-9]{1,3}\b' "${TEXT[@]}" 2>/dev/null \
    | grep -vE "$ALLOW" | sort -u -t: -k1,1 -k3,3 | head -12 | sed 's/^/  △ /' || echo "  ✓ 알려진 대역만 씁니다"
fi

echo ""
echo "════════════════════════════════════════"
if [ "$BAD" -gt 0 ]; then
  echo "✗ 막아야 할 것 $BAD 건 · 참고 $WARN 건"
  echo "  고친 뒤 다시 올리세요. 이미 푸시했다면 히스토리에도 남아 있습니다."
  exit 1
fi
echo "✓ 통과 (참고 $WARN 건)"
exit 0
