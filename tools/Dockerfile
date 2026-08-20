# 가짜 데이터를 만드는 데만 쓰는 이미지.
#
# 왜 있나
# ───────
# tools/make_demo_data.py 는 엑셀과 PPT 를 만들어야 해서 openpyxl ·
# python-pptx · Pillow 가 필요하다. 그런데 이걸 쓰는 사람의 PC 에
# 파이썬이 깔려 있으리라는 보장이 없다 — 특히 윈도우에서는 없는 쪽이 보통이다.
#
# 「도커만 있으면 된다」를 지키려면 이 작업도 컨테이너 안에서 해야 한다.
# 그래서 작은 이미지를 하나 만들어 두고, demo.sh / demo.ps1 이 그걸 쓴다.
#
# 파이썬이 이미 깔려 있고 위 세 개가 있으면 그쪽을 먼저 쓴다.
# 그게 훨씬 빠르기 때문이다 (이미지 빌드 없이 바로 돈다).
#
#   docker build -t portfolio-tools tools
#   docker run --rm -v "$PWD:/w" -w /w portfolio-tools python tools/make_demo_data.py
FROM python:3.12-slim

# 판을 고정한다. 안 그러면 몇 달 뒤에 받은 사람과 지금 만든 사람이
# 다른 결과를 보게 된다.
RUN pip install --no-cache-dir \
        openpyxl==3.1.5 \
        python-pptx==1.0.2 \
        pillow==11.0.0

WORKDIR /w
