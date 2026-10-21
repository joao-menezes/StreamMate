# StreamMate Web — conversor de mídia e downloader do YouTube para a rede interna
FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/joao-menezes/StreamMate" \
      org.opencontainers.image.description="StreamMate Web — conversor de mídia e downloader do YouTube"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

COPY constants ./constants
COPY services ./services
COPY web ./web

RUN useradd --create-home --uid 1000 streammate \
    && mkdir -p /data && chown streammate /data
USER streammate

ENV PYTHONUNBUFFERED=1 \
    IMAGEIO_FFMPEG_EXE=/usr/bin/ffmpeg \
    STREAMMATE_DATA_DIR=/data \
    STREAMMATE_MAX_JOBS=2 \
    STREAMMATE_JOB_TTL_MINUTES=60 \
    STREAMMATE_MAX_UPLOAD_MB=2048 \
    STREAMMATE_ENABLE_YOUTUBE=true

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
