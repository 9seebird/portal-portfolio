# 자동 배포 켜기 — GitHub Actions + SSH

`git push` → 검사 통과 → **바로 서버 배포**. 5분 기다리지 않는다.

배포 자체는 서버의 `autodeploy.sh` 가 한다. 깃허브는 그걸 부르기만 하므로
**헬스체크와 되돌리기가 그대로 살아 있다** — 띄운 뒤 `/health` 가 대답하지
않으면 서버가 스스로 직전 커밋으로 돌아간다.

---

## 핵심 — 이 열쇠로는 셸을 못 얻는다

「서버 열쇠를 깃허브에 맡기는 게 찝찝하다」가 이 방식의 유일한 걱정이다.
`authorized_keys` 에 **강제 명령**을 걸어 없앤다.

```
command="/srv/portal/autodeploy.sh --force",no-pty,no-port-forwarding,... ssh-ed25519 AAAA...
```

이 열쇠로 붙으면 **무엇을 보내든** 배포 스크립트만 돌고 끊긴다.
`ssh ... cat /etc/passwd` 를 보내도 그 명령은 무시된다.
열쇠가 새어도 남이 할 수 있는 것은 「배포를 한 번 더 돌리는 것」뿐이다.

---

## 1. 서버에서 — 배포 전용 열쇠 만들기

**평소 쓰는 열쇠를 쓰면 안 된다.** 그건 셸이 열리는 열쇠다.

```bash
ssh-keygen -t ed25519 -f ~/.ssh/gha_deploy -N "" -C "github-actions-deploy"
```

만들어진 것 두 개:

| 파일 | 어디로 |
|---|---|
| `~/.ssh/gha_deploy` (비밀) | 깃허브 Secrets 의 `DEPLOY_SSH_KEY` |
| `~/.ssh/gha_deploy.pub` (공개) | 서버의 `authorized_keys` |

## 2. 서버에서 — 강제 명령을 걸어 등록

```bash
KEY="$(cat ~/.ssh/gha_deploy.pub)"
OPTS='command="/srv/portal/autodeploy.sh --force",no-pty,no-agent-forwarding,no-port-forwarding,no-user-rc,no-X11-forwarding'
printf '%s %s\n' "$OPTS" "$KEY" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

제대로 걸렸는지 확인 — **셸이 열리면 안 된다.**

```bash
ssh -i ~/.ssh/gha_deploy -o IdentitiesOnly=yes azureuser@127.0.0.1 "echo 셸이열렸다"
```

`셸이열렸다` 가 찍히면 **잘못된 것이다.** 배포 로그가 흘러가야 맞다.

## 3. 서버에서 — 붙여넣을 값 뽑기

```bash
echo "── DEPLOY_SSH_KEY ──";     cat ~/.ssh/gha_deploy
echo "── DEPLOY_HOST ──";        curl -s ifconfig.me; echo
echo "── DEPLOY_USER ──";        whoami
echo "── DEPLOY_KNOWN_HOSTS ──"; ssh-keyscan -t ed25519 127.0.0.1 2>/dev/null | sed "s|^127.0.0.1|$(curl -s ifconfig.me)|"
```

## 4. 깃허브에 넣기

`Settings → Secrets and variables → Actions → New repository secret`

| 이름 | 값 | 필수 |
|---|---|---|
| `DEPLOY_SSH_KEY` | `gha_deploy` 파일 **통째로** — `-----BEGIN` 줄부터 `-----END` 줄까지, 줄바꿈 포함 | ✓ |
| `DEPLOY_HOST` | 서버 주소 (도메인이나 공인 IP) | ✓ |
| `DEPLOY_USER` | `azureuser` | ✓ |
| `DEPLOY_KNOWN_HOSTS` | 위 `ssh-keyscan` 결과 한 줄 | ✓ |
| `DEPLOY_PORT` | SSH 포트. 22 면 **안 넣어도 된다** | |
| `SECRET_WORDS` | 로컬 `.secretwords` 내용 그대로 (유출 검사용) | ✓ |

`DEPLOY_SSH_KEY` 는 붙여넣을 때 **줄바꿈이 살아 있어야 한다.** 한 줄로 뭉개지면
`invalid format` 이 난다.

## 5. Azure 방화벽 확인

깃허브 러너는 IP 가 매번 바뀐다. 네트워크 보안 그룹(NSG)에서 SSH 를 특정 IP 로만
열어 두셨다면 러너가 못 들어온다.

```bash
# 서버에서 — 22번이 열려 있는지
sudo ss -ltnp | grep :22
```

Azure 포털 → 해당 VM → 네트워킹 → 인바운드 규칙에서 22번의 **원본**을 본다.
`Any` 면 그대로 되고, 특정 IP 목록이면 러너가 막힌다.
그 경우엔 웹훅 방식이나 폴링(`deploy/systemd/`)으로 가는 편이 낫다 —
깃허브 IP 대역은 4,000개가 넘고 수시로 바뀌어서 허용 목록으로 관리할 수 없다.

## 6. 시험

```bash
# 아무거나 하나 고쳐서
git commit --allow-empty -m "배포 시험"
git push
```

깃허브 저장소 → **Actions** 탭 → `검사와 배포` → `배포` job.
서버의 배포 로그가 그 화면에 그대로 흘러가고, 마지막에 이 줄이 나와야 한다.

```
✓ 배포 완료 · http://127.0.0.1:8081/health 응답함
```

---

## 잘 안 될 때

| 증상 | 원인 |
|---|---|
| `✗ 저장소 Secrets 에 다음이 없습니다: ...` | 이름 그대로 넣었는지 확인 (대소문자 구분) |
| `Host key verification failed` | `DEPLOY_KNOWN_HOSTS` 가 비었거나 서버 지문이 바뀜. 3번을 다시 |
| `Permission denied (publickey)` | 공개키가 `authorized_keys` 에 안 들어갔거나 파일 권한(600) |
| `invalid format` | `DEPLOY_SSH_KEY` 가 한 줄로 뭉개짐. 줄바꿈 포함해서 다시 |
| `✗ 서버에 커밋 안 된 변경이 있어 멈춥니다` | 서버에서 파일을 직접 고쳤다. `git checkout -- <파일>` |
| 접속 자체가 안 됨 (timeout) | 5번 — NSG 가 러너를 막고 있다 |

## 타이머(폴링)는 어떻게 하나

이 방식을 쓰면 `deploy/systemd/` 의 타이머는 **안 켜도 된다.**

켜 두면 안전망이 되긴 한다 — 깃허브가 서버에 닿지 못한 날에도 결국 배포된다.
그때는 겹치지 않게 간격을 늘린다 (`autodeploy.timer` 의 `OnUnitActiveSec=30min`).
`autodeploy.sh` 는 `flock` 으로 겹쳐 도는 것을 막으므로 둘이 부딪히지는 않는다.
