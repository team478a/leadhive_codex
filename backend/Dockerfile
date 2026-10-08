FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.lock ./
RUN grep -v '^-e git+' requirements.lock > /tmp/requirements.lock && \
    python -m pip install --upgrade pip && \
    python -m pip install -r /tmp/requirements.lock

COPY pyproject.toml alembic.ini ./
COPY app ./app
COPY migrations ./migrations
RUN python -m pip install --no-deps . && \
    useradd --create-home --uid 10001 leadhive && \
    chown -R leadhive:leadhive /app

USER leadhive

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
