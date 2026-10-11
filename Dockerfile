# --- Base commune : dépendances + code ---------------------------------------
FROM python:3.12-slim AS base

# Pas de fichiers .pyc, journaux affichés immédiatement
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    COLONIE_DB=/data/colonie.db

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# --- Tests : base + pytest (jamais déployé) ----------------------------------
FROM base AS test
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests ./tests
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]

# --- Production (dernière étape = cible par défaut) ---------------------------
FROM base AS prod

# Utilisateur non-root avec le même UID/GID que dhafer (1000),
# pour que data/colonie.db reste copiable sans sudo
RUN groupadd -g 1000 colonie \
    && useradd -u 1000 -g 1000 -M -s /usr/sbin/nologin colonie \
    && mkdir -p /data && chown colonie:colonie /data

USER colonie
EXPOSE 8000

HEALTHCHECK --interval=5m --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/sante', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
