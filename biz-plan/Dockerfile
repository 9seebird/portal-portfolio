# 회사 표준: 베이스 이미지는 python:3.13-slim 으로 고정한다 (latest/3/alpine 금지)
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Seoul

WORKDIR /app

COPY requirements.txt .
# --root-user-action=ignore : 도커 이미지 안에서는 root 가 정상인데,
#   pip 가 "root 로 돌리지 마세요" 경고를 찍는다. 그 줄만 지운다.
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt

COPY app ./app

# 이 앱은 파일을 저장하지 않는다. 받아서 메모리에서 처리하고 버린다.
# 그래서 /data 도 두지 않는다.

EXPOSE 8080

# 계산은 1초 안쪽이지만, 엑셀 3개를 만들 때가 조금 길다. 넉넉히 잡는다.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-keep-alive", "75"]
