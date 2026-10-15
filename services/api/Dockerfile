FROM python:3.12-slim

WORKDIR /app

COPY services/api/requirements.txt services/api/requirements.txt
RUN pip install --no-cache-dir -r services/api/requirements.txt

COPY services/api/src services/api/src
COPY services/api/alembic.ini services/api/alembic.ini
COPY services/api/alembic services/api/alembic
COPY src src

ENV PYTHONPATH=/app/services/api/src:/app/src
ENV PYTHONDONTWRITEBYTECODE=1

RUN mkdir -p /app/artifacts

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
