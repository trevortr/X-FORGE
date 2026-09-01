FROM python:3.11-slim

WORKDIR /srv/physchem
COPY services/physchem/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY libs ./libs
COPY services/physchem/app ./app

EXPOSE 12005
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "12005"]
