FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# libpq for psycopg2; build tools only needed if a wheel is missing
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Set INSTALL_ML=true to include Prophet/BERTopic (much larger image)
ARG INSTALL_ML=false
COPY requirements.txt requirements-ml.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && if [ "$INSTALL_ML" = "true" ]; then pip install -r requirements-ml.txt; fi \
    && python -m spacy download en_core_web_sm

COPY . .

RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
CMD ["celery", "-A", "workflows.pipeline", "worker", "--loglevel=info"]
