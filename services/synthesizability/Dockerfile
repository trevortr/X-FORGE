FROM debian:bookworm-slim AS rascore-model

ARG RASCORE_REF=cb77db503ee5cbf0e8bb8963df6e5b76b3a94f06
ARG RASCORE_MODEL_SHA256=7ca8461207e76ded1224f393e7bdb21973b5c6caece2a4e550e6396efe2cf9f7

RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /model \
    && curl --fail --location \
        "https://raw.githubusercontent.com/reymond-group/RAscore/${RASCORE_REF}/RAscore/models/XGB_chembl_ecfp_counts/model.pkl" \
        --output /model/model.pkl \
    && echo "${RASCORE_MODEL_SHA256}  /model/model.pkl" | sha256sum --check --strict

FROM python:3.11-slim

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libexpat1 \
        libgomp1 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/synthesizability
COPY services/synthesizability/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /opt/rascore/XGB_chembl_ecfp_counts
COPY --from=rascore-model /model/model.pkl /opt/rascore/XGB_chembl_ecfp_counts/model.pkl
COPY libs ./libs
COPY services/synthesizability/app ./app

ENV RASCORE_MODEL_PATH=/opt/rascore/XGB_chembl_ecfp_counts/model.pkl

EXPOSE 12002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "12002"]
