# 자동 배포 켜기 (서버에서 한 번만)

`git push` 만 하면 서버가 알아서 받아 띄우게 만드는 설정이다.
깃허브가 서버를 부르는 것이 아니라, **서버가 5분에 한 번 물어보는** 방식이다.
바깥에서 들어오는 문을 열지 않고, 서버 접속 열쇠를 깃허브에 맡기지 않아도 된다.

> **먼저 읽을 것 —** 지금 이 저장소는 **GitHub Actions 로 배포한다**
> (`deploy/github-actions/README.md`). 푸시하면 바로 배포되므로 이 타이머는
> 켜지 않아도 된다.
>
> 그래도 켤 만한 경우는 둘이다.
> * 깃허브에 SSH 열쇠를 두고 싶지 않다 → Actions 대신 이것만 쓴다
> * 안전망이 필요하다 → 둘 다 켜고, 아래 `OnUnitActiveSec` 을 **30min** 으로 늘린다
>   (`autodeploy.sh` 가 `flock` 으로 겹쳐 도는 것을 막으므로 부딪히지 않는다)

## 1. 값이 맞는지 먼저 본다

`autodeploy.service` 의 두 줄이 이 서버와 맞아야 한다.

```ini
User=azureuser
WorkingDirectory=/srv/portal
```

확인:

```bash
whoami          # → azureuser 여야 한다
pwd             # 저장소 폴더에서 → /srv/portal
```

다르면 파일을 고친 뒤 다음으로 간다.

## 2. 손으로 한 번 돌려 본다

타이머를 걸기 전에 스크립트 자체가 도는지 본다. `--dry` 는 무엇을 할지 보기만 한다.

```bash
cd /srv/portal
./autodeploy.sh --dry
```

- `새 커밋 ...` 이 뜨거나 아무 말 없이 끝나면 정상이다
- `✗ 서버에 커밋 안 된 변경이 있어 멈춥니다` 가 뜨면 **서버에서 파일을 직접 고친 것이다.**
  서버는 받기만 하는 곳이므로 `git checkout -- <그 파일>` 로 되돌린다

## 3. 설치한다

```bash
sudo cp /srv/portal/deploy/systemd/autodeploy.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now autodeploy.timer
```

## 4. 확인한다

```bash
systemctl list-timers autodeploy.timer     # 다음 실행 시각
systemctl status autodeploy.service        # 마지막 실행 결과
tail -f /srv/portal/autodeploy.log         # 배포 기록
```

## 평소에

`git push` 하고 5분쯤 기다리면 반영된다. 급하면 손으로 당긴다.

```bash
sudo systemctl start autodeploy.service    # 지금 한 번
cd /srv/portal && ./autodeploy.sh --force  # 새 커밋이 없어도 다시 띄우기
```

## 끄기

```bash
sudo systemctl disable --now autodeploy.timer
```

끈 뒤에는 예전처럼 `./deploy.sh` 로 직접 배포하면 된다.

## 무엇이 자동으로 되고, 무엇이 안 되나

| | 자동 |
|---|---|
| 새 커밋 받기 · 이미지 다시 만들기 · 띄우기 | ✓ |
| 새 앱의 `.env` 만들기 (`setup.sh`) | ✓ |
| 띄운 뒤 `/health` 확인, 실패하면 **직전 커밋으로 되돌리기** | ✓ |
| 씨앗 다시 심기 (`seed_demo.py --force`) | ✗ 손으로 |
| DB 내용 (8082 로 들어가 화면에서 고친 것) | ✗ 애초에 깃에 없다 |

씨앗을 자동으로 돌리지 않는 이유는, 그것이 **데이터를 지우고 다시 넣는** 일이기 때문이다.
배포 때마다 자동으로 돌면 방문자가 만들어 둔 화면이 소리 없이 사라진다.
