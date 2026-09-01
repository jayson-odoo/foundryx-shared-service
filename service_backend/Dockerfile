# Multi-stage build for the Foundryx EMS FastAPI backend.
# Same image serves the API, the Celery workers, and Celery beat (command override).
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Production stage ────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Runtime native deps:
#  - postgresql-client → pg_isready (start.sh db wait)
#  - curl              → container healthcheck
#  - WeasyPrint stack (libglib/pango/cairo/gdk-pixbuf/ffi) → F2 PDF render;
#    without these the PDF task dies with "cannot load library 'libgobject-2.0-0'".
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    curl \
    libglib2.0-0 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libcairo2 \
    libffi8 \
    shared-mime-info \
    fonts-dejavu-core \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 appuser

COPY --from=builder /root/.local /home/appuser/.local
RUN chown -R appuser:appuser /home/appuser/.local && \
    chmod -R +x /home/appuser/.local/bin
ENV PATH=/home/appuser/.local/bin:$PATH

COPY . .
RUN chmod +x start.sh && chown -R appuser:appuser /app

USER appuser

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -fsS http://localhost:8001/health || exit 1

ENTRYPOINT ["/bin/sh", "/app/start.sh"]
