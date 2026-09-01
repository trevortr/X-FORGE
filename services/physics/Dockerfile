FROM python:3.11-slim

WORKDIR /srv/physics
COPY services/physics/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY libs ./libs
COPY services/physics/app ./app

EXPOSE 12006
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "12006"]
