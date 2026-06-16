# Stage 1: Build frontend static assets
FROM node:22-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.12-slim
WORKDIR /app

# Install system deps (Node.js required for MCP filesystem server via npx)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copy Python source and install (pyproject.toml packages.find covers app*;
# hello_agents is kept importable via PYTHONPATH below)
COPY pyproject.toml ./
COPY app/ app/
COPY hello_agents/ hello_agents/
RUN pip install --no-cache-dir .

ENV PYTHONPATH=/app

# Copy built frontend (served by FastAPI at /, /assets, /static)
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Data directories for persistent volumes
RUN mkdir -p /app/memory/agent-sessions

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
