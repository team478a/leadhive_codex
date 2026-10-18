FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

ARG LEADHIVE_GIT_COMMIT=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LEADHIVE_GIT_COMMIT=${LEADHIVE_GIT_COMMIT} \
    BROWSER_FORM_DELIVERY_ENABLED=false \
    BROWSER_FORM_ANALYSIS_ENABLED=false

WORKDIR /app

COPY backend/requirements.lock ./backend-requirements.lock
COPY backend/browser_worker/requirements.lock ./browser-worker-requirements.lock
RUN grep -v '^-e ' backend-requirements.lock > /tmp/backend-requirements.lock && \
    python -m pip install --upgrade pip && \
    python -m pip install -r /tmp/backend-requirements.lock && \
    python -m pip install -r browser-worker-requirements.lock

COPY backend/app ./app
COPY backend/browser_worker ./browser_worker
RUN useradd --create-home --uid 10001 leadhive && \
    chown -R leadhive:leadhive /app

USER leadhive

CMD ["python", "-m", "browser_worker"]
