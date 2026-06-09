# syntax=docker/dockerfile:1

# ── Stage 1: build React frontend ─────────────────────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
# Empty string → API_BASE resolves to "" (same-origin), so fetch("/costs") works
ENV VITE_API_URL=""
RUN npm run build

# ── Stage 2: Python backend ────────────────────────────────────────────────────
FROM python:3.11-slim
WORKDIR /app

# prophet/cmdstanpy requires a C++ toolchain to compile CmdStan
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ build-essential wget \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1
# cmdstanpy writes CmdStan here during install
ENV HOME=/app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    python -c "import cmdstanpy; cmdstanpy.install_cmdstan()"

COPY backend/*.py ./
COPY --from=frontend /build/dist ./static

# Hugging Face Spaces requires port 7860
EXPOSE 7860

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
