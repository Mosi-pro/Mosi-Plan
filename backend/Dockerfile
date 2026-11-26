FROM python:3.13-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# pg_dump für Backups (PostgreSQL 17 passend zum Datenbank-Container)
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client-17 curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
RUN useradd -u 1000 -m mosi && mkdir -p /data && chown mosi /data
USER mosi
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=5 CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1
CMD ["sh", "-c", "python -m app.cli wait-db && alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' --workers 1"]
