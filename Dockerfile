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

# Use Tsinghua mirror for faster downloads (国内构建加速)
# 海外部署可删除这一段，直接用默认源
RUN sed -i 's|http://deb.debian.org/debian|https://mirrors.tuna.tsinghua.edu.cn/debian|g' /etc/apt/sources.list.d/debian.sources \
    && sed -i 's|http://security.debian.org/debian-security|https://mirrors.tuna.tsinghua.edu.cn/debian-security|g' /etc/apt/sources.list.d/debian.sources

# Install system deps (Node.js required for MCP filesystem server via npx)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONPATH=/app
ENV PIP_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/

# Copy Python source and install (pyproject.toml packages.find covers app*;
# hello_agents is kept importable via PYTHONPATH below)
COPY pyproject.toml ./
COPY app/ app/
COPY hello_agents/ hello_agents/
COPY skills/ skills/
RUN pip install --no-cache-dir .

# Copy built frontend (served by FastAPI at /, /assets, /static)
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Data directories for persistent volumes
RUN mkdir -p /app/memory/agent-sessions

EXPOSE 18000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "18000"]
