FROM python:3.11-slim

WORKDIR /srv/orchestrator
COPY services/orchestrator/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY libs ./libs
COPY services/orchestrator/app ./app

CMD ["python", "-m", "app.main", "--pipeline", "/config/pipeline.yaml", "--services", "/config/services.yaml"]
