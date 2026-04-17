FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --upgrade pip setuptools wheel

# Copy requirements.txt if it exists, otherwise install minimal packages
COPY requirements.txt* ./

RUN if [ -f requirements.txt ]; then \
        pip install -r requirements.txt; \
    else \
        pip install --no-cache-dir \
            fastapi \
            uvicorn[standard] \
            slack-bolt \
            sqlalchemy \
            psycopg2-binary \
            redis \
            celery \
            python-dotenv \
            pydantic \
            requests \
            python-dateutil \
            httpx; \
    fi

# Copy application code
COPY . .

# Create non-root user for security
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/api/health')" || exit 1

CMD ["uvicorn", "apps.slack-bot.main:app", "--host", "0.0.0.0", "--port", "8000"]
