FROM python:3.11-slim

ENV MPLBACKEND=svg \
    MPLCONFIGDIR=/tmp/matplotlib

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libexpat1 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/visualizer
COPY services/visualizer/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/visualizer/app ./app

EXPOSE 12010
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "12010"]
