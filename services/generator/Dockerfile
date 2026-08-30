FROM python:3.11-slim

ARG REINVENT4_REF=v4.8
ARG REINVENT_PROCESSOR=cpu

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        git \
        libx11-6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --branch "${REINVENT4_REF}" --depth 1 \
        https://github.com/MolecularAI/REINVENT4.git /opt/reinvent4 \
    && cd /opt/reinvent4 \
    && python install.py "${REINVENT_PROCESSOR}" -d none

WORKDIR /srv/generator
COPY services/generator/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/generator/app ./app

EXPOSE 12000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "12000"]
