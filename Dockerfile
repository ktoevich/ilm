# Recommended deployment target: any host that runs a long-lived container with
# a persistent Postgres (Railway, Render, Fly.io, a plain VPS).
#
# Why not serverless: one analysis downloads and stitches satellite tiles and
# runs OpenCV over the mosaic. That regularly exceeds a serverless function's
# time budget, opencv+numpy sit close to the bundle size limit, and the cache
# that makes repeat requests cheap cannot survive a per-request process.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# opencv-python-headless still needs libgl/glib at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY backend/ ./backend/

WORKDIR /app/backend

# Static files are collected at build time so the image is immutable and
# whitenoise's manifest storage has something to hash.
RUN DJANGO_DEBUG=True python manage.py collectstatic --noinput

RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

EXPOSE 8000

# Two workers with threads: the work is I/O bound on tile downloads, and each
# analysis holds a decoded mosaic in memory, so process count stays low.
#
# Shell form so $PORT expands: Railway (and most PaaS hosts) inject the port
# the router forwards to. Plain `docker run -p 8000:8000` keeps working.
CMD gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers 2 \
    --threads 4 \
    --timeout 120 \
    --access-logfile -
