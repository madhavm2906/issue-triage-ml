FROM python:3.12-slim AS backend

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv/triage

COPY requirements.txt requirements-ml.txt requirements-github.txt ./
RUN python -m pip install --no-cache-dir \
    -r requirements.txt -r requirements-ml.txt -r requirements-github.txt

COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini compare_body.py ./

FROM node:24-bookworm-slim AS frontend-build

WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM nginx:1.28-alpine AS dashboard

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build /src/dist/ /usr/share/nginx/html/
