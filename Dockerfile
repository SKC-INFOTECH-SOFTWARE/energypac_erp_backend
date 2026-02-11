# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim

# Prevent Python from writing pyc files
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# ---------------------------------------
# Install system dependencies (mysqlclient)
# ---------------------------------------
RUN apt-get update && apt-get install -y \
    build-essential \
    pkg-config \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------
# Install Python dependencies
# ---------------------------------------
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# ---------------------------------------
# Copy project
# ---------------------------------------
COPY . .

# ---------------------------------------
# Create staticfiles & collect static
# ---------------------------------------
RUN mkdir -p /app/staticfiles && \
    python manage.py collectstatic --noinput

# ---------------------------------------
# Create non-root user
# ---------------------------------------
ARG UID=10001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/nonexistent" \
    --shell "/sbin/nologin" \
    --no-create-home \
    --uid "${UID}" \
    appuser

# Give permissions
RUN chown -R appuser:appuser /app

USER appuser

# ---------------------------------------
# Expose Port
# ---------------------------------------
EXPOSE 4000

# ---------------------------------------
# Start Gunicorn
# ---------------------------------------
CMD ["gunicorn", "erp_energypac.wsgi:application", \
     "--bind", "0.0.0.0:4000", \
     "--workers", "2", \
     "--timeout", "120", \
     "--log-level", "info"]