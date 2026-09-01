FROM python:3.11-slim

ARG PYTORCH_VERSION=2.13.0

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libexpat1 \
        libx11-6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/admet-ai
COPY services/admet_ai/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==${PYTORCH_VERSION}+cpu" \
    && pip install --no-cache-dir -r requirements.txt

COPY services/admet_ai/admet.py ./admet.py
COPY services/admet_ai/endpoint.py ./endpoint.py
COPY services/admet_ai/entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

EXPOSE 12007
CMD ["./entrypoint.sh"]
