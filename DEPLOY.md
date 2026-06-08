# 织镜 ZHÌJÌNG — 生产级部署指南

## 快速开始

```bash
# 1. 配置环境
cp .env.example .env
# 编辑 .env 填入真实密钥

# 2. (可选) 从JSON迁移到SQLite
STORE_BACKEND=sqlite python3 backend/store.py

# 3. 启动
docker-compose up -d

# 或直接运行
python3 -m uvicorn backend.server:app --host 0.0.0.0 --port 8899
```

## 存储后端

默认使用 JSON 文件 (`data/memory_store.json`)。
切换到 SQLite：在 `.env` 中设置 `STORE_BACKEND=sqlite`。

迁移现有数据：
```bash
python3 -c "from backend.store import migrate_json_to_sqlite; n=migrate_json_to_sqlite(); print(f'{n} 会话已迁移')"
```

## API 认证

**dev 模式**（默认）：无需 token，速率限制 60/min。

**单 Key**：`.env` 中设置 `API_TOKEN=your-secret-key`

**多 Key**：`.env` 中设置 `API_KEYS={"key1":{"name":"张三","rate_limit":30},"key2":{"name":"李四","rate_limit":20}}`

请求头：`Authorization: Bearer <key>`

## 监控与运维

- Health: `GET /api/health`
- Metrics: `GET /api/metrics`
- Memory: `GET /api/memory/{session_id}`
- 结构化日志：所有日志以 JSON 格式输出到 stdout
- Docker 日志：`docker-compose logs -f zhijing`
