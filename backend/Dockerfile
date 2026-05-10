FROM python:3.11-slim

WORKDIR /app

# System dependencies for pdf2image, opencv, poppler
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x /app/entrypoint.sh

# Universal entrypoint handles: wait-for-postgres, alembic upgrade,
# one-time SQLite import. CMD is then exec'd as the actual service.
ENTRYPOINT ["/app/entrypoint.sh"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
