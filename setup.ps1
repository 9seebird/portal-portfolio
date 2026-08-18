# =====================================================================
# 처음 한 번 — 깃에서 받은 직후에 돌린다.
#
#   .\setup.ps1              로컬 시험용 (80 을 그대로)
#   .\setup.ps1 -Server      사내 서버처럼 (호스트 nginx 뒤, 127.0.0.1:8081)
#
# 하는 일은 setup.sh 와 같다. 특히 **같은 서비스 토큰을 네 파일에 맞춰
# 넣는 것**이 핵심이다. 한 글자만 달라도 포털이 앱을 못 부르는데
# 화면에는 "Unauthorized" 만 나오고 아무 단서가 없다.
# =====================================================================
param([switch]$Server)

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Ok($m)   { Write-Host "  " -NoNewline; Write-Host "OK" -ForegroundColor Green -NoNewline; Write-Host " $m" }
function Warn($m) { Write-Host "  " -NoNewline; Write-Host "!!" -ForegroundColor Yellow -NoNewline; Write-Host " $m" }

function New-Secret {
    $b = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
    ([Convert]::ToBase64String($b) -replace '[=+/]','').Substring(0,40)
}

# .env 는 BOM 없이 써야 한다. docker compose 가 BOM 을 키 이름의 일부로 읽는다.
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
function Read-Env($p)  { if (Test-Path $p) { Get-Content $p -Raw -Encoding UTF8 } else { "" } }
function Write-Env($p, $t) { [IO.File]::WriteAllText((Resolve-Path $p), $t, $Utf8NoBom) }
function Get-Val($p, $k) {
    $t = Read-Env $p
    $m = [regex]::Match($t, "(?m)^$k=(.*)$")
    if ($m.Success) { $m.Groups[1].Value.Trim() } else { "" }
}
function Set-Val($p, $k, $v) {
    $t = Read-Env $p
    if ($t -match "(?m)^$k=") { $t = [regex]::Replace($t, "(?m)^$k=.*$", "$k=$v") }
    else { if ($t -and -not $t.EndsWith("`n")) { $t += "`n" }; $t += "$k=$v`n" }
    Write-Env $p $t
}

# ── 1. .env 만들기 ───────────────────────────────────────────
Write-Host ""
Write-Host "> .env 준비"
# 폴더 이름을 적어 두지 않는다. 새 서비스를 붙일 때마다 이 목록을 고치게
# 하면 언젠가 반드시 빠뜨린다. .env.example 이 있는 폴더는 전부 대상이다.
$svcDirs = Get-ChildItem -Directory | Where-Object { $_.Name -notlike '_*' } |
           Where-Object { Test-Path (Join-Path $_.Name '.env.example') } |
           ForEach-Object { $_.Name }

foreach ($d in $svcDirs) {
    $ex = Join-Path $d '.env.example'
    $en = Join-Path $d '.env'
    if (Test-Path $en) { Ok "$d\.env - 이미 있음 (건드리지 않음)" }
    else { Copy-Item $ex $en; Ok "$d\.env - 새로 만듦" }
}

# ★ 한 단 아래에 있는 것도 있다.
#   it-asset 은 백엔드가 자기 설정을 따로 쓴다 - it-asset\backend\.env.deploy.
#   위 반복문은 **최상위 폴더만** 보므로 이 파일이 안 만들어지고,
#   compose 의 env_file 이 없는 파일을 가리켜 it-asset 만 조용히 실패한다.
#   내 PC 에는 예전에 만든 파일이 남아 있어서 안 보이고, **새로 받은 사람만**
#   걸린다.
foreach ($x in @('it-asset\backend\.env.deploy')) {
    if (-not (Test-Path "$x.example")) { continue }
    if (Test-Path $x) { Ok "$x - 이미 있음 (건드리지 않음)" }
    else { Copy-Item "$x.example" $x; Ok "$x - 새로 만듦" }
}

# ── 2. 비밀값 ────────────────────────────────────────────────
Write-Host ""
Write-Host "> 비밀값"
$jwt = Get-Val 'portal\.env' 'JWT_SECRET'
if (-not $jwt -or $jwt -eq 'change-this-to-a-long-random-string') {
    Set-Val 'portal\.env' 'JWT_SECRET' (New-Secret); Ok "JWT_SECRET 새로 만듦"
} else { Ok "JWT_SECRET 그대로 둠" }

$tok = Get-Val 'portal\.env' 'AUDIT_TOKEN'
if (-not $tok -or $tok -eq 'change-this-shared-token') {
    $tok = New-Secret; Set-Val 'portal\.env' 'AUDIT_TOKEN' $tok; Ok "AUDIT_TOKEN 새로 만듦"
} else { Ok "AUDIT_TOKEN 그대로 둠" }

# 여기가 핵심 - 같은 값을 옆 앱들에 맞춘다.
# portal 은 이 토큰의 주인이므로 건너뛴다. 나머지는 전부 맞춘다.
foreach ($d in $svcDirs) {
    if ($d -eq 'portal' -or $d -eq 'proxy') { continue }
    $en = Join-Path $d '.env'
    if (-not (Test-Path $en)) { continue }
    Set-Val $en 'AUDIT_TOKEN' $tok; Ok "$d\.env - 포털과 같은 토큰으로 맞춤"

    # 앱이 포털을 부를 주소. 비어 있으면 자기 등록을 건너뛰어
    # 관리자 화면에 안 뜬다.
    # ★ 줄이 **아예 없을 때도** 넣어 준다.
    #   전에는 "있으면 채운다" 였는데, 그러면 .env.example 에 그 줄을 안 적어 둔
    #   앱은 영영 비어 있게 된다. 그 앱은 뜰 때마다 조용히 자기 등록을 건너뛴다.
    if ((Read-Env $en) -match '(?m)^PORTAL_API_URL=') {
        if (-not (Get-Val $en 'PORTAL_API_URL')) {
            Set-Val $en 'PORTAL_API_URL' 'http://demo-portal:8080'; Ok "$d\.env - PORTAL_API_URL 채움"
        }
    } else {
        Add-Content -Path $en -Value 'PORTAL_API_URL=http://demo-portal:8080' -Encoding UTF8
        Ok "$d\.env - PORTAL_API_URL 넣음 (없었음)"
    }
    # 로컬은 DEV_MODE 를 켜 둬도 되지만 서버에서는 반드시 꺼야 한다.
    if ((Read-Env $en) -match '(?m)^DEV_MODE=') {
        $curDev = Get-Val $en 'DEV_MODE'
        if (-not $curDev -or ($Server -and $curDev -ne 'false')) {
            $devVal = if ($Server) { 'false' } else { 'true' }
            Set-Val $en 'DEV_MODE' $devVal; Ok "$d\.env - DEV_MODE=$devVal"
        }
    } else {
        # 줄이 아예 없으면 넣어 준다 (PORTAL_API_URL 과 같은 이유).
        $devVal = if ($Server) { 'false' } else { 'true' }
        Add-Content -Path $en -Value "DEV_MODE=$devVal" -Encoding UTF8
        Ok "$d\.env - DEV_MODE=$devVal 넣음 (없었음)"
    }
}

# ── 3. 프록시 포트 ───────────────────────────────────────────
Write-Host ""
Write-Host "> 프록시 포트"
if ($Server) { $pub = '127.0.0.1:8081:80'; $cookie = '1'; $note = '서버 - 호스트 nginx 뒤에 섭니다' }
else         { $pub = '80:80';             $cookie = '0'; $note = '로컬 - 80 을 그대로 씁니다' }
if (Test-Path 'proxy\.env') { Set-Val 'proxy\.env' 'PROXY_PUBLISH' $pub }
Ok "$note  (PROXY_PUBLISH=$pub)"
if ((Read-Env 'portal\.env') -match '(?m)^COOKIE_SECURE=') {
    Set-Val 'portal\.env' 'COOKIE_SECURE' $cookie; Ok "COOKIE_SECURE=$cookie"
}

# ── 4. 남은 것 ───────────────────────────────────────────────
Write-Host ""
$key = Get-Val 'portal\.env' 'OPENAI_API_KEY'
if (-not $key -or $key.StartsWith('발급받은')) {
    Warn "portal\.env 의 OPENAI_API_KEY 를 채우세요. (이것만은 사람이 넣어야 합니다)"
} else { Ok "OPENAI_API_KEY 들어 있음" }

Write-Host ""
Write-Host "──────────────────────────────────────────────"
Write-Host "다음:"
Write-Host "  docker network create demo-net    # 처음 한 번만"
Write-Host "  .\deploy.ps1                        # 전부 띄우기"
Write-Host ""
