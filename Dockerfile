# Multi-stage production Dockerfile for Enterprise Email Ingestion Gateway
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# --- Runtime Stage ---
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/home/appuser/.local/bin:$PATH

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root security user
RUN groupadd -g 1000 appgroup && \
    useradd -u 1000 -g appgroup -s /bin/bash -m appuser

# Copy installed Python packages from builder
COPY --from=builder /root/.local /home/appuser/.local

# Copy application source code
COPY pyproject.toml .
COPY src/ ./src/

# Install application package
RUN chown -R appuser:appgroup /home/appuser /app
USER appuser
RUN pip install --no-cache-dir --user -e .

# Create data directories with secure permissions
USER root
RUN mkdir -p /app/Auto_download_email && \
    chown -R appuser:appgroup /app/Auto_download_email && \
    chmod 700 /app/Auto_download_email

USER appuser

VOLUME ["/app/Auto_download_email"]

# Healthcheck validating configuration and database
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD email-ingestion validate || exit 1

ENTRYPOINT ["email-ingestion"]
CMD ["watch", "--interval", "60"]
