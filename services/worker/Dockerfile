FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY services/api/requirements.txt services/api/requirements.txt
COPY services/worker/requirements.txt services/worker/requirements.txt
RUN pip install --no-cache-dir -r services/api/requirements.txt -r services/worker/requirements.txt

COPY services/api/src services/api/src
COPY services/worker/src services/worker/src
COPY src src

ENV PYTHONPATH=/app/services/api/src:/app/services/worker/src:/app/src
ENV PYTHONDONTWRITEBYTECODE=1

RUN mkdir -p /app/artifacts

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

CMD ["celery", "-A", "shared.celery_app", "worker", "--loglevel=INFO", "--hostname=worker@%h"]
