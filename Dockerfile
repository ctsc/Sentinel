# =============================================================
# Sentinel — Multi-stage Dockerfile
# =============================================================
# Targets:
#   backend  — Python app (all producers + consumer + API via run_all.py)
#   frontend — Nginx serving static React build + reverse proxy to backend
# =============================================================

# ----- Stage: backend -----
FROM python:3.12-slim AS backend

WORKDIR /app

# Install system deps for spaCy / cassandra-driver
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libev-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    python -m spacy download en_core_web_lg

# Copy application code
COPY ingestion/ ./ingestion/
COPY processing/ ./processing/
COPY api/ ./api/
COPY data/ ./data/
COPY run_all.py .

CMD ["python", "run_all.py"]

# ----- Stage: frontend-build -----
FROM node:20-alpine AS frontend-build

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ .

ARG VITE_MAPBOX_TOKEN=""
ARG VITE_WS_URL=""
ARG VITE_API_URL=""
ENV VITE_MAPBOX_TOKEN=${VITE_MAPBOX_TOKEN}
ENV VITE_WS_URL=${VITE_WS_URL}
ENV VITE_API_URL=${VITE_API_URL}

RUN npm run build

# ----- Stage: frontend (nginx) -----
FROM nginx:alpine AS frontend

RUN rm /etc/nginx/conf.d/default.conf
COPY infrastructure/nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
