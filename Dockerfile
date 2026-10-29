# Multi-stage production Dockerfile for PIXL 2.0 API & Workers
FROM python:3.12-slim-bookworm AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock .
RUN pip install --no-cache-dir --prefix=/install --require-hashes -r requirements.lock

# Final production stage
FROM python:3.12-slim-bookworm AS runner

WORKDIR /app

# Install runtime dependencies including FFmpeg for media inspection and libpq
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Create non-root user for security
RUN groupadd -r pixl && useradd -r -g pixl -d /app -s /sbin/nologin pixl

# Copy application source code
COPY . /app
RUN mkdir -p /app/local_storage && chown -R pixl:pixl /app

USER pixl

EXPOSE 8000

# Default command: run FastAPI production server via Uvicorn
CMD ["uvicorn", "pixl.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--workers", "1"]

