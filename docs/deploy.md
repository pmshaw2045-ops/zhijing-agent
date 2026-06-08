# 织镜 ZHÌJÌNG — 生产级部署指南

## 快速开始

```bash
# 1. 配置环境
cp .env.example .env
# 编辑 .env 填入真实密钥

# 2. 启动
python3 -m uvicorn backend.server:app --host 0.0.0.0 --port 8899
```

## 存储后端

默认使用 JSON 文件 (`data/memory_store.json`)。当前 ~360 会话，JSON 文件足够，暂不需要迁移 SQLite。

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
