FROM python:3.11-slim

WORKDIR /app

# 의존성을 먼저 복사해야 코드만 바뀌었을 때 이 층이 캐시된다.
# COPY . . 을 먼저 하면 매 배포마다 pip install 을 다시 돈다.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY static/ ./static/
COPY manage.py migrate_roles.py check_llm.py ./

# SQLite 파일이 들어갈 자리. compose 에서 볼륨으로 덮어쓴다.
RUN mkdir -p /app/data

EXPOSE 8080

# 컨테이너는 UTC 로 도는데 기록 시각을 한국 시간으로 남기므로
# zoneinfo 가 tzdata 를 찾을 수 있어야 한다 (requirements 에 포함).
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
