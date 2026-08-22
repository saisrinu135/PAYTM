# ---- builder: compile wheels once, keep the runtime image clean -----------
FROM python:3.12-slim AS builder

WORKDIR /srv
RUN pip install --no-cache-dir --upgrade pip
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


# ---- runtime -------------------------------------------------------------
FROM python:3.12-slim

# ffmpeg is a hard runtime requirement: services/voice.py shells out to it to
# decode webm/opus from the browser into 16k mono PCM. Without it every audio
# endpoint fails at ingest.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/* \
 && rm -rf /wheels

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AUDIO_DIR=/srv/media \
    MODELS_DIR=/srv/models

WORKDIR /srv
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY app/ ./app/
COPY seeds/ ./seeds/
COPY scripts/ ./scripts/

# Non-root. media/ is a mounted volume the app writes utterance audio into.
RUN useradd --system --uid 1001 appuser \
 && mkdir -p /srv/media /srv/models \
 && chown -R appuser:appuser /srv/media /srv/models
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
