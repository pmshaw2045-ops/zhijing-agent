# 织镜 ZHÌJÌNG — 生产级优化执行计划

> 日期：2026-06-07
> 状态：执行中

## 进度

| # | 事项 | 状态 |
|---|------|:--:|
| 1 | API 版本控制 | ✅ |
| 2 | 依赖锁定 | ✅ |
| 3 | 结构化日志 | ✅ |
| 4 | 前端拆分 | ⏳ |
| 5 | Docker Compose | ⏳ |
| 6 | JSON → SQLite | 📋 |
| 7 | 鉴权升级 | 📋 |

---

## 4. 前端拆分

**目标**：app.js (871行) → sse.js + render.js + console.js + chat.js

**方案**：
- `sse.js`：SSE 连接 + 事件分发
- `render.js`：renderReport() 模板函数
- `console.js`：clog/clogSection/clearConsole/Console面板
- `chat.js`：addMessage/sendMessage/记忆显示/快速按钮

**风险**：全局变量（sessionId/API_BASE/currentMode等）需挂 window.xxx

---

## 5. Docker Compose

**目标**：自动重启 + 环境隔离

**文件**：`docker-compose.yml`
```yaml
services:
  zhijing:
    build: .
    ports: ["8899:8899"]
    restart: always
    volumes: ["./data:/app/data"]
    env_file: .env
```

---

## 6. JSON → SQLite

**方案**：
1. 新建 `store.py` — SQLiteBackend
2. MemorySystem 加 `_backend` 属性，默认为 JSON，可通过 `STORE_BACKEND=sqlite` 切换
3. 迁移脚本 `scripts/migrate_json_to_sqlite.py`
4. WAL 模式 + 连接池

**schema**：
```sql
CREATE TABLE sessions (id TEXT PRIMARY KEY, data JSON, updated_at REAL)
CREATE TABLE long_term (key TEXT PRIMARY KEY, value JSON)
```

**双写验证**：迁移期间同时写 JSON 和 SQLite，读从 SQLite。

---

## 7. 鉴权升级

**内部阶段**（当前）：API Key + HMAC 签名
```python
# 生成：python -c "import secrets; print(secrets.token_urlsafe(32))"
API_KEYS = {"key_xxx": {"role": "admin", "rate_limit": 60}}
```

**SaaS 阶段**（未来）：OAuth2 + JWT + 租户隔离
