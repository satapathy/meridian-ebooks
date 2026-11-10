FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    IMPORT_DIR=/import

WORKDIR /srv

# Runtime deps only (pytest/httpx are for the test suite)
COPY requirements.txt .
RUN grep -viE '^(pytest|httpx)' requirements.txt > requirements.runtime.txt \
 && pip install --no-cache-dir -r requirements.runtime.txt

COPY app ./app

RUN useradd --create-home --uid 1000 meridian \
 && mkdir -p /data /import && chown meridian /data
USER meridian

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
