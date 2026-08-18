# 서버 배포 가이드 — IT 자산 포탈

대상: 우분투 24.04 서버 한 대 (2 vCPU / 4GB, 공용 IP 있음)
구성: nginx(정적+프록시) + FastAPI 컨테이너 + SQLite 파일. 포트 8081.
      (매뉴얼 포탈이 8080을 쓰는 것과 나란히 올라간다)

─────────────────────────────────────────────
0. 푸시 전 점검 (PC에서, 순서대로)
─────────────────────────────────────────────

# (1) 비밀번호가 코드에 없는지 — create_admin.py 기본값을 admin1234 로 되돌렸는지
git diff HEAD -- backend/scripts/create_admin.py

# (2) 비밀 파일이 추적 안 되는지 — 아무것도 안 나와야 정상
git ls-files | findstr /i ".env app.db lisence license.xlsx pc_list rental sw_userlist"

# (3) 커밋 + 푸시
git add .
git commit -m "자산관리: 라이선스 부여/회수, 직원 명단 개편, 배포 구성"
git push origin main

─────────────────────────────────────────────
1. 데이터 준비 (PC에서)
─────────────────────────────────────────────

# 로컬 Postgres → 서버로 가져갈 SQLite 파일
cd backend
python scripts\transfer_db.py `
  --source "postgresql+psycopg://asset_user:비밀번호@127.0.0.1:5432/asset_portal" `
  --dest   "sqlite+pysqlite:///../data/app.db" --yes

# 마이그레이션 위치 도장 (이걸 안 하면 서버에서 alembic 이 헛돈다)
$env:DATABASE_URL="sqlite+pysqlite:///../data/app.db"
python -m alembic stamp head
Remove-Item Env:DATABASE_URL

만들어진 data\app.db 를 서버로 복사한다 (scp, 또는 WinSCP):
  scp data\app.db 계정@서버IP:~/it-asset-portal/data/app.db

─────────────────────────────────────────────
2. 서버 준비 (최초 1회)
─────────────────────────────────────────────

# 스왑 2GB — RAM 1GiB 서버에서 도커 빌드가 죽지 않게. 이미 했으면 건너뜀
free -h && swapon --show
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Docker (이미 있으면 건너뜀)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker

─────────────────────────────────────────────
3. 배포 (서버에서)
─────────────────────────────────────────────

git clone <저장소주소> it-asset-portal && cd it-asset-portal
# (이후 업데이트는 git pull 후 아래 up --build 만 다시)

# 비밀 채우기
cp backend/.env.deploy.example backend/.env.deploy
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # 결과를 SECRET_KEY 에
nano backend/.env.deploy

# 데이터 파일 확인 (1번에서 올린 것)
ls -lh data/app.db

docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps      # 둘 다 healthy/running

curl localhost:8081/healthz          # ok
curl localhost:8081/api/healthz      # {"status":"ok"}

# 서버 관리자 비밀번호 설정 (로컬과 별개다!)
docker compose -f docker-compose.prod.yml exec \
  -e ADMIN_PASSWORD='새비밀번호' api python scripts/create_admin.py

─────────────────────────────────────────────
4. 방화벽 (Azure 포털)
─────────────────────────────────────────────

VM → 네트워킹 → 인바운드 규칙: TCP 8081 허용
원본은 반드시 "회사 고정 IP"로 제한. Any 로 열면 직원 명단·자산 정보가
전 세계에 노출된다. 접속: http://서버IP:8081

─────────────────────────────────────────────
5. 운영
─────────────────────────────────────────────

# 백업 (SQLite 는 실행 중 복사 금지 — 전용 명령 사용)
docker compose -f docker-compose.prod.yml exec api \
  python -c "import sqlite3; sqlite3.connect('/app/data/app.db').execute(\"VACUUM INTO '/app/data/backup.db'\")"
# data/backup.db 를 다른 곳에 보관

# 로그
docker compose -f docker-compose.prod.yml logs -f api

# 절대 하지 말 것: 서버에서 import_*.py 재실행 (웹에서 정리한 데이터가 엑셀 상태로 되돌아감)

─────────────────────────────────────────────
자주 물을 것
─────────────────────────────────────────────

Q. 로컬에서 계속 개발하다가 서버에 반영하려면?
   코드: git push → (서버) git pull → up -d --build
   데이터: 반영 안 됨. 서버 DB가 원본이 된 뒤로는 서버에서 직접 수정.
   (양쪽에서 따로 고치면 갈라진다 — 배포 후 데이터 관리는 서버에서만)

Q. 프론트가 API 주소를 어떻게 아나?
   localhost:3000/3001 에서 열면 개발용(localhost:8000),
   그 외(서버)에서는 같은 주소의 /api 로 자동 전환. 코드 수정 불필요.
