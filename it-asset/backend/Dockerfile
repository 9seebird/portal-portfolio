# IT 자산 포탈 백엔드 (서버 1GiB RAM 기준: SQLite + 단일 워커)
FROM python:3.12-slim

WORKDIR /app

# 의존성 먼저 복사 → 코드만 바뀌면 이 레이어는 캐시 재사용
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts ./scripts

# SQLite 파일이 이 볼륨에 놓인다 (compose 에서 ./data 마운트)
RUN mkdir -p /app/data

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
