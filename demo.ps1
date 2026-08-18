# =====================================================================
# 체험판을 한 번에 띄운다 (윈도우 PowerShell) — 서버의 demo.sh 와 짝이다.
#
#   .\demo.ps1                내 PC. 80 을 그대로 쓴다
#   .\demo.ps1 -Behind        앞에 nginx 를 둘 때 (127.0.0.1:8081 로만)
#
# 쓰는 법이 서버와 같다.
#
#   내 PC   .\demo.ps1
#   서버    ./demo.sh
#
# 하는 일
#   1. setup.ps1 로 .env 를 만들고 앱끼리 쓰는 토큰을 맞춘다
#   2. 그 위에 체험판 값을 덮어쓴다 (DEMO_MODE=1 · 계정 · 한도)
#   3. 가짜 데이터를 만든다
#   4. deploy.ps1 로 순서대로 띄운다
#   5. 각 앱 컨테이너 안에서 자료를 넣는다
#   6. 안전장치가 진짜로 막는지 바깥에서 확인한다
#
# 두 번째로 실행해도 안전하다. 이미 있는 것은 건드리지 않는다.
#
# 필요한 것은 **Docker Desktop 뿐**이다. 파이썬은 없어도 된다
# (없으면 데이터 만드는 일도 컨테이너 안에서 한다).
#
# 처음 실행 시 "이 시스템에서 스크립트를 실행할 수 없으므로" 오류가 나면:
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
# =====================================================================
[CmdletBinding()]
param([switch]$Behind, [int]$Port = 8090, [string[]]$Skip = @())

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$ROOT = $PSScriptRoot
Set-Location $ROOT

function Ok  ($m) { Write-Host "  ✓ $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function Bad ($m) { Write-Host "  ✗ $m" -ForegroundColor Red }
function Head($m) { Write-Host ''; Write-Host "▸ $m" -ForegroundColor Cyan }

# .env 는 BOM 없이 써야 한다. docker compose 가 BOM 을 키 이름의 일부로 읽는다.
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
function Read-Env($p)  { if (Test-Path $p) { Get-Content $p -Raw -Encoding UTF8 } else { "" } }
function Get-Val($p, $k) {
    $m = [regex]::Match((Read-Env $p), "(?m)^$k=(.*)$")
    if ($m.Success) { $m.Groups[1].Value.Trim() } else { "" }
}
# 값을 **덮어쓴다.** setup.ps1 은 비어 있을 때만 채우는데, 체험판 값은
# 그러면 안 된다. 이미 뭔가 들어 있어도 체험판 기준으로 되돌려 놓아야
# 다음 사람이 보는 화면이 늘 같다.
function Put($p, $k, $v) {
    $t = Read-Env $p
    if (-not $t) { Bad "$p 가 없습니다. setup.ps1 이 실패한 것 같습니다."; exit 1 }
    if ($t -match "(?m)^$k=") { $t = [regex]::Replace($t, "(?m)^$k=.*$", "$k=$v") }
    else { if (-not $t.EndsWith("`n")) { $t += "`n" }; $t += "$k=$v`n" }
    [IO.File]::WriteAllText((Resolve-Path $p), $t, $Utf8NoBom)
}

# ── 도커가 떠 있는지 ─────────────────────────────────────────
# Docker Desktop 이 꺼져 있으면 아래가 전부 알 수 없는 오류로 끝난다.
#
# ★ 있는지부터 본다. $ErrorActionPreference='Stop' 이라 명령 자체가 없으면
#   PowerShell 이 CommandNotFoundException 을 던지며 여기서 죽는데,
#   그 화면만 봐서는 무엇이 문제인지 알기 어렵다.
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Bad 'docker 명령을 찾지 못했습니다. Docker Desktop 을 설치하고 켜 주세요.'
    exit 1
}
docker info 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Bad 'Docker 가 응답하지 않습니다. Docker Desktop 을 켜고 다시 실행하세요.'
    exit 1
}

# ── 1. 평소 준비 ─────────────────────────────────────────────
Head '기본 준비 (setup.ps1)'
if ($Behind) { & "$ROOT\setup.ps1" -Server | Out-Null }
else         { & "$ROOT\setup.ps1"         | Out-Null }
Ok '.env · 토큰 맞춤'

# ── 2. 체험판 값 ─────────────────────────────────────────────
Head '체험판 설정'
Put 'portal\.env' 'DEMO_MODE'            '1'
Put 'portal\.env' 'DEMO_USER_ID'         'demo'
Put 'portal\.env' 'DEMO_PASSWORD'        'demo1234'
Put 'portal\.env' 'DEMO_CHAT_PER_IP_DAY' '20'
Put 'portal\.env' 'DEMO_TOKENS_PER_MONTH' '3000000'
Put 'portal\.env' 'DEMO_DB'              './data/demo.db'
Ok "DEMO_MODE=1 · 계정 demo · 챗 IP당 하루 20회"

# ★ 80 을 차지하지 않는다.
#   내 PC 에는 이미 뭔가 80 을 쓰고 있을 가능성이 높다. 체험판이 남의
#   자리를 뺏으면 안 된다. 서버(-Behind)는 앞의 nginx 가 80/443 을 맡는다.
if (-not $Behind) {
    Put 'proxy\.env' 'PROXY_PUBLISH' "$($Port):80"
    Ok "주소 http://localhost:$Port/  (바꾸려면 .\demo.ps1 -Port 9000)"
}

# 남이 올린 첨부를 볼 수 있는 계정. 체험판에서는 비워 둔다.
# 방문자끼리 서로 올린 파일이 보이면 안 된다.
Put 'portal\.env' 'UPLOAD_VIEWERS' ''
Ok '첨부 열람 계정 없음 (방문자끼리 서로 안 보임)'

# ★ 개발 모드는 반드시 끈다.
#   setup.ps1 은 「내 PC」 모드에서 DEV_MODE=true 로 둔다 — 포털 헤더가
#   없어도 테스트 계정으로 통과시켜서, 앱 하나만 띄워 놓고 고칠 때 편하다.
#   체험판에서는 그게 **인증을 통째로 건너뛰는 뒷문**이 된다.
#   (컨테이너가 밖에 열려 있지 않아도, 한 겹으로 버티게 두지 않는다)
Get-ChildItem -Directory | Where-Object { Test-Path (Join-Path $_.Name '.env') } |
  ForEach-Object {
      $f = Join-Path $_.Name '.env'
      if ((Read-Env $f) -match '(?m)^DEV_MODE=') { Put $f 'DEV_MODE' 'false' }
  }
Ok 'DEV_MODE=false (모든 앱)'

# 자산 앱은 자기 서명키를 따로 쓴다. 예시 값이 그대로면 뜨자마자 죽는다.
$aenv = 'it-asset\backend\.env.deploy'
if ((Test-Path $aenv) -and ((Get-Val $aenv 'SECRET_KEY') -like '여기에*')) {
    $b = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
    Put $aenv 'SECRET_KEY' (([Convert]::ToBase64String($b) -replace '[=+/]','').Substring(0,40))
    Ok '자산 앱 서명키 새로 만듦'
}

# ── 3. AI 키 ─────────────────────────────────────────────────
$key = Get-Val 'portal\.env' 'OPENAI_API_KEY'
if (-not $key -or $key -like '발급받은*') {
    Write-Host ''
    Warn 'portal\.env 의 OPENAI_API_KEY 가 비어 있습니다.'
    Warn '챗을 뺀 나머지는 전부 돌아갑니다. 챗까지 보려면 키를 넣고 다시 실행하세요.'
}

# ── 4. 가짜 데이터 ───────────────────────────────────────────
#
# 엑셀·PPT 를 만들어야 해서 openpyxl · python-pptx · Pillow 가 필요하다.
# 이 PC 에 있으면 그걸 쓰고, 없으면 컨테이너 안에서 돌린다.
# 「Docker Desktop 만 있으면 된다」를 지키려는 것이다.
Head '가짜 데이터'
$havePy = $false
foreach ($py in @('python', 'python3', 'py')) {
    # ★ 있는지부터 본다. 없는 명령을 그냥 부르면 예외로 스크립트가 죽는다.
    #   윈도우에는 python.exe 가 「앱 설치」 창을 여는 껍데기로 깔려 있기도 해서,
    #   실제로 꾸러미를 불러 보는 것까지 확인해야 한다.
    if (-not (Get-Command $py -ErrorAction SilentlyContinue)) { continue }
    & $py -c "import openpyxl, pptx, PIL" 2>$null
    if ($LASTEXITCODE -eq 0) { & $py tools\make_demo_data.py; $havePy = $true; break }
}
if (-not $havePy) {
    Ok '이 PC 에 파이썬 꾸러미가 없어 컨테이너로 만듭니다 (처음 한 번만 좀 걸립니다)'
    docker build -q -t chat-portal-tools tools | Out-Null
    docker run --rm -v "$($ROOT):/w" -w /w chat-portal-tools python tools/make_demo_data.py
}

# ── 5. 띄우기 ────────────────────────────────────────────────
#
# 폴더 이름이 곧 앱 이름이다. -Skip 으로 몇 개를 빼고 띄울 수 있다.
$targets = Get-ChildItem -Directory |
    Where-Object { Test-Path (Join-Path $_.Name 'docker-compose.yml') } |
    Where-Object { $Skip -notcontains $_.Name } |
    ForEach-Object { $_.Name }
if ($Skip.Count) { Ok "안 띄우는 앱: $($Skip -join ', ')  (코드는 저장소에 있습니다)" }

& "$ROOT\deploy.ps1" @targets

# ── 6. 각 앱에 자료 넣기 ─────────────────────────────────────
#
# ★ 왜 컨테이너 안에서 하는가.
#   앱의 표 구조와 검사 규칙은 그 앱만 안다. 밖에서 DB 에 직접 쓰면
#   「그 앱의 업로드로는 통과 못 할 자료」가 화면에 앉게 되고, 그러면
#   파서가 망가져도 데모는 멀쩡해 보인다. 각 앱이 자기 파서를 거쳐
#   받아들이게 두면, 자료가 보인다는 것 자체가 그 앱이 돈다는 확인이 된다.
Head '앱에 자료 넣기'

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
function Seed($container, $label, [string[]]$cmd) {
    $running = docker ps --format '{{.Names}}' | Where-Object { $_ -eq $container }
    if (-not $running) { Warn "$container 가 떠 있지 않습니다 — $label 건너뜀"; return }
    Write-Host "  $label"
    # docker 는 실패해도 예외를 던지지 않고 종료 코드만 남긴다.
    # $cmd 는 배열인데, 네이티브 명령에 넘기면 원소 하나가 인자 하나가 된다.
    docker exec -i $container $cmd
    if ($LASTEXITCODE -ne 0) { Warn "$label 자료를 넣지 못했습니다." }
}

Seed 'demo-asset-api'     '자산관리'      @('python','scripts/seed_demo.py')
Seed 'demo-leave-anomaly' '연차 이상패턴' @('python','-m','app.seed_demo')
Seed 'demo-manual-import' '매뉴얼'        @('python','-m','app.seed_demo')

# ── 6-1. 안 띄운 앱은 목록에서도 뺀다 ────────────────────────
#
# 앱은 뜰 때 포털에 자기를 등록하고, 그 기록은 portal/data 에 **남는다**.
# 한 번 등록되고 나면 다음에 그 앱을 안 띄워도 목록에는 그대로 있어서,
# 눌러 보면 502 가 난다 — 「있는 줄 알고 눌렀는데 없다」가 되는 것이다.
# 컨테이너를 안 띄우는 것만으로는 부족하고, 등록도 지워야 한다.
foreach ($s in $Skip) {
    # ★ 바깥을 홑따옴표로 둔다. 쌍따옴표 문자열 안에서 `" 로 이스케이프하면
    #   네이티브 명령(docker)에 넘어가는 과정에서 따옴표가 사라져 깨진다.
    $py = 'import os,sqlite3;c=sqlite3.connect(os.environ.get("PORTAL_DB","./data/portal.db"));' +
          'c.execute("DELETE FROM services WHERE id=?",("' + $s + '",));c.commit()'
    docker exec -i demo-portal python -c $py 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { Ok "앱 목록에서도 뺐습니다: $s" }
    else { Warn "$s 를 앱 목록에서 빼지 못했습니다 (포털이 안 떠 있을 수 있습니다)" }
}

# 포털은 뜰 때 스스로 넣는다 (app/demo.py 의 seed_people).
# 앱들이 등록한 서비스를 켜는 것도 포털이 한다 — 앱이 언제 등록할지
# 밖에서는 알 수 없어서, 포털이 한동안 지켜보다가 켠다.

# ── 7. 진짜로 막혀 있는지 ────────────────────────────────────
# 설정 파일을 읽는 것이 아니라 **바깥에서 요청을 보내** 확인한다.
# 「고쳤다고 생각했는데 안 고쳐진 것」은 이 방법으로만 잡힌다.
#
# 도커 네트워크 안에서 프록시를 이름으로 부른다. 호스트에서 localhost 로
# 부르면 -Behind 로 띄웠을 때 주소가 달라지고, 파이썬이 없을 수도 있다.
Head '안전장치 확인'
Start-Sleep -Seconds 4
docker run --rm --network demo-net -v "$($ROOT)\tools:/t" `
    python:3.12-slim python /t/check_demo.py http://demo-proxy

Write-Host ''
Write-Host '──────────────────────────────────────────────'
Write-Host '  아이디  demo'
Write-Host '  비밀번호 demo1234'
Write-Host ''
if ($Behind) { Write-Host '  앞의 nginx 를 127.0.0.1:8081 로 넘기도록 설정하세요.' }
else         { Write-Host "  http://localhost:$Port/" -ForegroundColor Cyan }
Write-Host ''
