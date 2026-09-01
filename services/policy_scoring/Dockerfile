FROM python:3.11-slim

WORKDIR /srv/policy-scoring
COPY services/policy_scoring/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY libs ./libs
COPY services/policy_scoring/app ./app

EXPOSE 12003
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "12003"]
