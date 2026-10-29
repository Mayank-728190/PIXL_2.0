# Multi-stage production Dockerfile for PIXL 2.0 API & Workers
FROM python:3.12-slim-bookworm as builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final production stage
FROM python:3.12-slim-bookworm as runner

WORKDIR /app

# Install runtime dependencies including FFmpeg for media inspection and libpq
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Create non-root user for security
RUN groupadd -r pixl && useradd -r -g pixl -d /app -s /sbin/nologin pixl

# Copy application source code
COPY . /app
RUN chown -R pixl:pixl /app

USER pixl

EXPOSE 8000

# Default command: run FastAPI production server via Uvicorn
CMD ["uvicorn", "pixl.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
