# =====================================================================
# 새 앱을 프록시에 붙인다.  apps\서비스ID.conf 를 만들어 준다.
#
#   .\new-app.ps1 meeting-room
#   .\new-app.ps1 meeting-room -Container meetingroom
#   .\new-app.ps1 it-asset -Container asset-web -Port 80
#
# -Port 는 컨테이너 **안쪽** 포트다. 표준 규칙 v2 로 만든 앱은 8080 이라
# 안 줘도 되지만, nginx 로 화면을 주는 앱은 80 인 경우가 많다.
# 이 값이 틀리면 화면에 502 Bad Gateway 가 뜬다.
#
# 컨테이너 이름을 안 주면 서비스 ID 에서 하이픈을 뺀 것을 쓴다
# (ai-report → aireport. 기존 앱이 그렇게 되어 있다).
# docker-compose.yml 의 container_name 과 반드시 같아야 한다.
#
# 만든 뒤:
#   1) .\deploy.ps1 proxy        설정을 다시 읽힌다
#   2) 포털 관리자 화면에서 접근 범위·담당자를 정하고 켠다
# =====================================================================
param(
    [Parameter(Mandatory=$true)][string]$Id,
    [string]$Container = "",
    [int]$Port = 8080,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# 서비스 ID 규칙: 영문 소문자·숫자·하이픈. 주소와 컨테이너 이름에 그대로 쓰인다.
if ($Id -notmatch '^[a-z0-9]([a-z0-9-]*[a-z0-9])?$') {
    Write-Host "서비스 ID 는 영문 소문자·숫자·하이픈만 쓸 수 있습니다. (예: meeting-room)" -ForegroundColor Red
    exit 1
}
if ($Container -eq "") { $Container = $Id -replace '-','' }

$template = Join-Path $here "apps\_TEMPLATE.conf.txt"
$target   = Join-Path $here "apps\$Id.conf"

if (-not (Test-Path $template)) {
    Write-Host "본보기 파일이 없습니다: $template" -ForegroundColor Red
    exit 1
}
if ((Test-Path $target) -and (-not $Force)) {
    Write-Host "이미 있습니다: apps\$Id.conf" -ForegroundColor Yellow
    Write-Host "덮어쓰려면 -Force 를 붙이세요." -ForegroundColor Yellow
    exit 1
}

# nginx 변수 이름에는 하이픈을 쓸 수 없다. meeting-room → meeting_room
$var = $Id -replace '-','_'

$text = Get-Content $template -Raw -Encoding UTF8
# 안내용 머리말(본보기 설명)은 빼고 설정만 남긴다
$cut = $text.IndexOf("location /__ID__/")
if ($cut -gt 0) { $text = $text.Substring($cut) }

$head = @"
# ── $Id ──────────────────────────────────────────────────────
#   서비스 ID   : $Id      (포털 관리자 화면의 ID 와 같아야 한다)
#   컨테이너    : $Container
#   접속 주소   : /$Id/
#   안쪽 포트   : $Port
#   만든 날짜   : $(Get-Date -Format 'yyyy-MM-dd')
#
# portal.conf 의 server 블록 안으로 include 된다.
# ─────────────────────────────────────────────────────────────

"@

$text = $text -replace '__PORT__', "$Port"
$text = $text -replace '__CONTAINER__', $Container
$text = $text -replace '__VAR__', $var
$text = $text -replace '__ID__', $Id

# BOM 없는 UTF-8 로 저장한다. BOM 이 붙으면 nginx 가 첫 줄을 못 읽는다.
$enc = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($target, $head + $text, $enc)

Write-Host "만들었습니다: apps\$Id.conf" -ForegroundColor Green
Write-Host ""
Write-Host "다음 순서:" -ForegroundColor Cyan
Write-Host "  1. $Container 컨테이너가 demo-net 에 떠 있는지 확인 (안쪽 포트 $Port)"
Write-Host "  2. .\deploy.ps1 proxy"
Write-Host "  3. 포털 관리자 화면 → 서비스 관리 → $Id → 접근 범위·담당자 정하고 켜기"
Write-Host "  4. http://<서버>/$Id/ 로 접속 확인"
