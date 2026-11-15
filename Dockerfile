FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

RUN useradd --create-home --uid 10001 app \
 && mkdir -p /app/.cache /app/logs \
 && chown -R app:app /app

COPY --chown=app:app engine ./engine
COPY --chown=app:app api ./api
COPY --chown=app:app scripts ./scripts

USER app
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
