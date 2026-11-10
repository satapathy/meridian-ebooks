# ---- build stage: has a compiler so packages without prebuilt wheels (e.g. Pillow on 32-bit ARM) can be built
FROM python:3.12-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_EXTRA_INDEX_URL=https://www.piwheels.org/simple

RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libjpeg-dev zlib1g-dev \
 && rm -rf /var/lib/apt/lists/*

# Runtime deps only (pytest/httpx are for the test suite)
COPY requirements.txt .
RUN grep -viE '^(pytest|httpx)' requirements.txt > requirements.runtime.txt \
 && pip install --prefix=/install -r requirements.runtime.txt


# ---- runtime stage
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    IMPORT_DIR=/import

# shared libraries Pillow links against when it was compiled in the build stage
RUN apt-get update \
 && apt-get install -y --no-install-recommends libjpeg62-turbo \
 && rm -rf /var/lib/apt/lists/*

COPY --from=build /install /usr/local

WORKDIR /srv
COPY app ./app

RUN useradd --create-home --uid 1000 meridian \
 && mkdir -p /data /import && chown meridian /data
USER meridian

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
