FROM python:3.11-slim

WORKDIR /srv/binding
COPY services/binding/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libexpat1 \
        libgomp1 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY libs ./libs
COPY services/binding/app ./app

EXPOSE 12004
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "12004"]
