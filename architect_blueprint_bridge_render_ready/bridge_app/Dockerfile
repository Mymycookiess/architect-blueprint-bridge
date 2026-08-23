FROM python:3.12-slim

WORKDIR /app
COPY bridge_app/requirements.txt /app/bridge_app/requirements.txt
RUN pip install --no-cache-dir -r /app/bridge_app/requirements.txt

COPY bridge_app /app/bridge_app
COPY blueprint_engine /app/blueprint_engine

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["uvicorn", "bridge_app.app:app", "--host", "0.0.0.0", "--port", "8080"]
