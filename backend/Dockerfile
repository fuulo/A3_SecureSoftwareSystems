# One stateless API instance. docker-compose.yml runs several behind the load
# balancer; certificates, the signing key and Firebase credentials are mounted
# at run time, never built into the image.
FROM python:3.13.2-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY tls-policy.json ./
COPY backend backend

RUN useradd --system --uid 10001 api && mkdir logs && chown api logs
USER api

EXPOSE 8000
CMD ["python", "-m", "backend.tls_server", "--host", "0.0.0.0", "--port", "8000"]
