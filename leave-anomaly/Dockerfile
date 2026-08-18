# 회사 표준: 베이스 이미지는 python:3.13-slim 으로 고정한다 (latest/3/alpine 금지)
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Seoul

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# 데이터는 /data 한 곳에만 쌓인다
RUN mkdir -p /data/uploads

# 컨테이너 안 포트는 8080. 바깥 포트는 열지 않는다(앞단 nginx 가 경로로 넘겨줌).
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
