FROM python:3.12-slim

WORKDIR /app

COPY bridge_app/requirements.txt /app/bridge_app/requirements.txt
COPY blueprint_engine/requirements.txt /app/blueprint_engine/requirements.txt
RUN pip install --no-cache-dir \
    -r /app/bridge_app/requirements.txt \
    -r /app/blueprint_engine/requirements.txt

COPY bridge_app /app/bridge_app
COPY blueprint_engine /app/blueprint_engine

ENV PYTHONUNBUFFERED=1
ENV BLUEPRINT_OUTPUT_ROOT=/app/production_runs

EXPOSE 10000

CMD ["sh", "-c", "uvicorn bridge_app.app:app --host 0.0.0.0 --port ${PORT:-10000}"]
