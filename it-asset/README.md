# IT Asset Portal

사내 IT 자산, 직원, IP, 소프트웨어, 라이선스, 렌탈 계약을 관리하는 FastAPI 기반 자산 관리 도구입니다.

## Stack

- FastAPI
- SQLAlchemy
- Alembic
- PostgreSQL
- Static HTML/CSS/JS frontend
- Docker Compose for local PostgreSQL

## Backend

```powershell
docker compose up -d db
cd backend
python -m pip install -r requirements.txt
python -m alembic upgrade head
python scripts\create_admin.py
python -m uvicorn app.main:app --reload
```

API 문서: `http://localhost:8000/docs`

기본 관리자 계정:

- ID: `admin`
- PW: `admin1234`

관리자 비밀번호를 바꾸려면:

```powershell
$env:ADMIN_USERNAME="admin"
$env:ADMIN_PASSWORD="new-password"
python scripts\create_admin.py
```

## Frontend

```powershell
cd frontend
npm run start
```

프론트엔드: `http://localhost:3000`

화면의 API URL은 `http://localhost:8000`으로 둡니다.
