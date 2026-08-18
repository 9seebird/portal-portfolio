# =====================================================================
# 배포 스크립트 (윈도우 PowerShell) — 서버의 deploy.sh 와 짝이다.
#
#   .\deploy.ps1                    전부
#   .\deploy.ps1 manual-import      하나만
#   .\deploy.ps1 portal proxy       여럿
#
#   .\deploy.ps1 -Pull              깃에서 당긴 뒤 띄운다
#   .\deploy.ps1 portal -Logs       띄운 뒤 로그를 붙여서 본다
#
# 서버와 쓰는 법이 같다. 폴더로 들어가지 않고 **뿌리에서 이름만** 댄다.
#
#   내 PC   .\deploy.ps1 manual-import
#   서버    ./deploy.sh  manual-import
#
# 딱 하나 다른 것: 서버는 깃에서 당기는 것이 기본이고, 여기는 아니다.
# 내 PC 는 내가 고치는 곳이라, 띄울 때마다 당기면 방금 고친 것과 부딪친다.
# 당기고 싶으면 -Pull 을 붙인다.
#
# 처음 실행 시 "이 시스템에서 스크립트를 실행할 수 없으므로" 오류가 나면:
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
# =====================================================================
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Targets = @(),
    [switch]$Pull,
    [switch]$Logs
)

# 한글이 깨지지 않게 콘솔 출력 인코딩을 UTF-8 로 맞춘다.
# 이 파일은 UTF-8(BOM 포함)로 저장돼 있어야 한다. BOM 이 없으면
# Windows PowerShell 5.1 이 파일을 CP949 로 읽어서 주석·메시지가
# "?맫 붕" 처럼 깨진다.
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$OutputEncoding = [System.Text.Encoding]::UTF8

# 하나가 실패해도 나머지는 계속 올린다. 중간에 멈춰 버리면
# "리포트가 안 뜨네" 하고 봤더니 포털도 안 떠 있는 상황이 된다.
$ErrorActionPreference = 'Continue'
$ROOT = $PSScriptRoot
$NET  = 'demo-net'
Set-Location $ROOT

function Ok  ($m) { Write-Host "  ✓ $m" -ForegroundColor Green }
function Bad ($m) { Write-Host "  ✗ $m" -ForegroundColor Red }
function Note($m) { Write-Host "    $m" -ForegroundColor DarkGray }
function Head($m) {
    Write-Host ''
    Write-Host '========================================' -ForegroundColor DarkGray
    Write-Host "▸ $m" -ForegroundColor Cyan
    Write-Host '========================================' -ForegroundColor DarkGray
}

# ── 도커가 떠 있는지 ─────────────────────────────────────────
# Docker Desktop 이 꺼져 있으면 아래가 전부 알 수 없는 오류로 끝난다.
# 무엇이 문제인지 여기서 먼저 말해 주는 편이 낫다.
docker info 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Bad 'Docker 가 응답하지 않습니다. Docker Desktop 을 켜고 다시 실행하세요.'
    exit 1
}

# ── 깃에서 당기기 (물어봤을 때만) ────────────────────────────
if ($Pull -and (Test-Path (Join-Path $ROOT '.git'))) {
    Write-Host '▸ git pull'
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        Bad '당기지 못했습니다. 고치던 파일이 있는지 보세요.'
        Note 'git status --short'
        exit 1
    }
}

# ── 공용 네트워크 ────────────────────────────────────────────
# 없으면 컨테이너들이 서로를 이름으로 못 찾는다.
docker network inspect $NET 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "▸ 네트워크 $NET 생성"
    docker network create $NET | Out-Null
}

# ── 대상 정하기 ──────────────────────────────────────────────
if ($Targets.Count -gt 0) {
    $list = $Targets
} else {
    # 밑줄로 시작하는 폴더는 작업용·참고용이다. 띄울 대상이 아니다.
    $list = Get-ChildItem -Directory |
            Where-Object { $_.Name -notlike '_*' } |
            Where-Object { Test-Path (Join-Path $_.Name 'docker-compose.yml') } |
            ForEach-Object { $_.Name }
}

# 순서가 중요하다.
#
#   portal 이 맨 처음   앱들은 뜨자마자 포털에 "나 여기 있다"고 등록한다.
#                       포털이 아직 없으면 그 등록이 실패하고, 그 앱만
#                       관리자 화면에 안 뜬다. 화면에는 아무 단서도 없다.
#   proxy 가 맨 마지막   뒤쪽 서비스가 먼저 떠 있어야 첫 요청부터 502 가 안 난다.
$ordered = @()
$ordered += $list | Where-Object { $_ -eq 'portal' }
$ordered += $list | Where-Object { $_ -ne 'portal' -and $_ -ne 'proxy' }
$ordered += $list | Where-Object { $_ -eq 'proxy' }

$failed = @()

foreach ($name in $ordered) {
    $dir = Join-Path $ROOT $name
    if (-not (Test-Path (Join-Path $dir 'docker-compose.yml'))) {
        Bad "$name — docker-compose.yml 이 없습니다. 건너뜁니다."
        continue
    }

    Head $name
    Push-Location $dir
    try {
        # .env 가 필요한데 없으면 띄우지 않는다.
        # 없는 채로 뜨면 JWT_SECRET 이 비어 첫 요청부터 500 이 난다.
        if ((Test-Path '.env.example') -and -not (Test-Path '.env')) {
            Bad '.env 가 없습니다.'
            Note '뿌리에서  .\setup.ps1  을 한 번 돌리면 만들어 줍니다.'
            $failed += "$name (.env 없음)"
            continue
        }

        # 같은 이름의 컨테이너를 다른 폴더가 쥐고 있으면 여기서 멈춘다.
        #
        # container_name 은 도커 전체에서 유일해야 한다. 예전에 다른 곳에서
        # 띄워 둔 컨테이너가 같은 이름을 쓰고 있으면, build 를 다 끝낸 뒤에야
        # "Conflict. The container name is already in use" 로 실패한다.
        # 무엇이 쥐고 있는지 먼저 알려주는 편이 낫다.
        $conflict = $false
        Select-String -Path 'docker-compose.yml' -Pattern '^\s*container_name:\s*([A-Za-z0-9_.-]+)' |
          ForEach-Object { $_.Matches[0].Groups[1].Value } |
          ForEach-Object {
            $owner = docker inspect $_ --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' 2>$null
            if ($LASTEXITCODE -eq 0 -and $owner) {
                # 윈도우는 경로를 슬래시로도 역슬래시로도 적는다. 맞춰서 견준다.
                $a = ($owner -replace '\\', '/').TrimEnd('/').ToLower()
                $b = ($dir   -replace '\\', '/').TrimEnd('/').ToLower()
                if ($a -ne $b) {
                    Bad "'$_' 이름을 다른 곳에서 쓰고 있습니다."
                    Note "쓰는 곳 : $owner"
                    Note "정리    : docker rm -f $_"
                    $conflict = $true
                }
            }
          }
        if ($conflict) { $failed += "$name (컨테이너 이름 충돌)"; continue }

        docker compose up -d --build
        if ($LASTEXITCODE -ne 0) {
            Bad "$name — 빌드 또는 실행 실패"
            Note "로그 : docker compose -f $name\docker-compose.yml logs --tail 50"
            $failed += $name
            continue
        }
        Ok $name

        # ── 프록시는 설정을 다시 읽혀야 한다 ──────────────────
        # conf.d 와 apps 는 볼륨으로 붙어 있어서 파일은 바로 보이지만,
        # nginx 는 뜰 때 한 번만 읽는다. 컨테이너가 이미 떠 있으면 compose 는
        # "Running" 이라고만 하고 아무것도 하지 않는다. 그래서 앱 conf 를
        # 새로 넣어도 그 경로가 404 로 남는다.
        if ($name -eq 'proxy') {
            docker exec demo-proxy nginx -t 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                docker exec demo-proxy nginx -s reload 2>&1 | Out-Null
                Ok 'nginx 설정 다시 읽음'
            } else {
                Bad 'nginx 설정에 문제가 있어 그대로 둡니다.'
                Note '고친 뒤 다시 실행하세요. 지금은 옛 설정으로 돌고 있습니다.'
                Note 'docker exec demo-proxy nginx -t'
                $failed += 'proxy (설정 오류)'
            }
        }
    } finally { Pop-Location }
}

Write-Host ''
Write-Host '========================================' -ForegroundColor DarkGray
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

if ($failed.Count -gt 0) {
    Write-Host ''
    Bad ("실패: " + ($failed -join ', '))
    exit 1
}

Write-Host ''
Write-Host '확인:  http://localhost/            포털'
if ($Targets.Count -eq 1 -and $Targets[0] -ne 'portal' -and $Targets[0] -ne 'proxy') {
    Write-Host "       http://localhost/$($Targets[0])/"
}
Write-Host ''

# ── 로그 붙여 보기 ───────────────────────────────────────────
# 방금 고친 것이 제대로 도는지 보려면 결국 로그를 본다. 그 한 줄을
# 따로 찾아 치지 않아도 되게 여기서 이어 준다. Ctrl+C 로 빠져나온다.
if ($Logs -and $ordered.Count -gt 0) {
    $t = $ordered[-1]
    Write-Host "로그 ($t) — Ctrl+C 로 빠져나옵니다" -ForegroundColor DarkGray
    Push-Location (Join-Path $ROOT $t)
    try { docker compose logs -f --tail 50 } finally { Pop-Location }
}
