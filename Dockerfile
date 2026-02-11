# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim as base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies (mysqlclient)
RUN apt-get update && apt-get install -y \
    build-essential \
    pkg-config \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
ARG UID=10001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/nonexistent" \
    --shell "/sbin/nologin" \
    --no-create-home \
    --uid "${UID}" \
    appuser

# Install Python deps
COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    python -m pip install -r requirements.txt

# Copy source code
COPY . .

# 🔥 IMPORTANT: Create staticfiles directory and give permission
RUN mkdir -p /app/staticfiles && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

EXPOSE 4000

CMD gunicorn erp_energypac.wsgi:application \
    --bind 0.0.0.0:4000 \
    --workers 2 \
    --timeout 120 \
    --log-level debug
