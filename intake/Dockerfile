FROM python:3.13-slim

# check-intake.sh 가 쓰는 것들. 없으면 「이유 없이 검사 항목이 통째로 비는」
# 모양이 되므로 못 박아 둔다.
RUN apt-get update && apt-get install -y --no-install-recommends \
        bash findutils grep sed gawk \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Seoul

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# 규칙과 예시. ★ 예시는 검사 대상이지 실행 대상이 아니다 — 아무것도 설치하지 않는다.
COPY rules ./rules
COPY samples ./samples
# 장부와 제출 이력이 쌓이는 곳. 볼륨을 안 붙였으므로 **컨테이너 안에만**
# 있고, 다시 띄우면 사라진다 (docker-compose.yml 의 설명 참고).
RUN mkdir -p /app/data

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
