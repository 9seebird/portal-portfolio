FROM python:3.11-slim

WORKDIR /app

# 버전을 requirements.txt 에 적어 두고 그걸 읽는다.
# 여기에 그대로 적으면 버전이 없어서, 다시 빌드하는 날마다 다른 것이 깔린다.
#
# --root-user-action=ignore : 도커 이미지 안에서는 root 가 정상인데,
#   pip 가 "root 로 돌리지 마세요" 경고를 찍는다. 그 줄만 지운다.
COPY requirements.txt .
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt

COPY main.py .
COPY index.html .
# 엑셀 라이브러리. index.html 에서 빼낸 것이라 함께 있어야 한다.
COPY xlsx.min.js .

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
