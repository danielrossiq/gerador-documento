# syntax=docker/dockerfile:1.7
# Um Dockerfile, três alvos: `api` (leve), `worker` (com LibreOffice) e `tools` (migrate/seed/cli).
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN useradd --create-home --uid 10001 app
COPY pyproject.toml ./
# instala só as dependências (camada cacheável) lendo o pyproject
RUN python - <<'PY' > /tmp/req.txt
import tomllib
d = tomllib.load(open("pyproject.toml", "rb"))["project"]
print("\n".join(d["dependencies"] + d["optional-dependencies"]["postgres"]))
PY
RUN pip install -r /tmp/req.txt
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY seed ./seed
RUN mkdir -p /app/data && chown -R app:app /app/data
USER app

FROM base AS api
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]

FROM base AS tools
CMD ["python", "-m", "app.cli", "--help"]

# Worker: mesmo código + LibreOffice headless (somente Writer) e fontes métricas compatíveis com o Office.
FROM base AS worker
USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends libreoffice-writer fonts-liberation2 fonts-crosextra-carlito \
      fonts-crosextra-caladea fonts-dejavu-core fontconfig \
 && rm -rf /var/lib/apt/lists/* \
 && fc-cache -f
USER app
ENV SOFFICE_PATH=soffice HOME=/home/app
EXPOSE 9191
CMD ["dramatiq", "app.worker.tasks", "--processes", "2", "--threads", "4"]
