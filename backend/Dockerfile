FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements-runtime.lock ./requirements-runtime.lock
RUN pip install --no-cache-dir --no-compile --require-hashes -r requirements-runtime.lock \
    && groupadd --system --gid 10001 crownd \
    && useradd --system --uid 10001 --gid crownd --home-dir /app --no-create-home crownd
COPY --chown=crownd:crownd . .

USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-access-log"]
