FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=8080 \
    HOME=/home/app

# LibreOffice is required for PDF/preview export.
# Fonts are kept generic so the image stays portable across VPS providers.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libreoffice-impress \
       fonts-liberation \
       fonts-dejavu-core \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --create-home --home-dir /home/app app

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

RUN mkdir -p /app/outputs/runs /home/app/.config/libreoffice \
    && chown -R app:app /app /home/app

USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).read()" || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
