FROM python:3.11-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY data/ ./data/

# 创建数据目录
RUN mkdir -p /app/data

# 环境变量（生产环境需覆盖）
ENV API_TOKEN=change-me-in-production
ENV APP_ENV=production
ENV PYTHONUNBUFFERED=1

EXPOSE 8899

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8899/api/health || exit 1

CMD ["python", "-m", "uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8899", "--log-level", "info"]
