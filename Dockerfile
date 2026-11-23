# Propelo Cloud: one image for the web app, the worker and migrations.
#   docker build -t propelo .
#   docker run propelo propelo cloud serve --host 0.0.0.0     (web, the default)
#   docker run propelo propelo cloud worker                   (background worker)
#   docker run propelo propelo cloud migrate                  (release step)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UPLOAD_DIR=/data/uploads
WORKDIR /app

COPY pyproject.toml README.md ./
COPY propelo ./propelo
RUN pip install ".[cloud,monitoring]" \
 && useradd --create-home --uid 10001 propelo \
 && mkdir -p /data/uploads && chown -R propelo /data

USER propelo
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT', '8000'), timeout=4).status == 200 else 1)" || exit 1
# Hosts such as Render name the port to listen on in PORT; 8000 otherwise.
CMD ["sh", "-c", "exec propelo cloud serve --host 0.0.0.0 --port ${PORT:-8000}"]
