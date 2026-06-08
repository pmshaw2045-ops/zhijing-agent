# 织镜 ZHÌJÌNG — 生产就绪度评估

> 评估日期：2026-06-08
> 下次评估：每主要架构变更后

---

## 一、当前状态总览

| 指标 | 数值 |
|---|---|
| 后端代码 | 28 模块 / 4,186 行 |
| 前端代码 | index.html 1,204 行 + app.js (870行/未使用) |
| 测试 | 93 backend (pytest) + 14 frontend (jest) = 107 |
| Lint | ruff 全过 |
| 部署 | Dockerfile + docker-compose.yml + GitHub Actions CI |
| 文档 | AGENTS.md + docs/ 结构清晰 |
| TODO/FIXME/DEPRECATED | 0 处残留 |
| 缓存 | 24h 报告缓存 + JSON 文件持久化记忆 |

---

## 二、分维度评估

### 2.1 架构设计 8/10 🟢

**优点**：
- Pipeline 模式：8 个 Phase 职责清晰，每个 Phase 由独立引擎处理
- IntentRegistry 作为 SSOT（单一真相来源），新增意图只需注册
- DecomposeEngine 使用 `json_mode=True` 强制 LLM 输出纯 JSON，根除了解析失败导致的模板回退
- DI 模式（`__init__` 实例变量）为多租户隔离做准备
- Prompt 数据注入规范（`goal_to_text`）统一自然语言渲染
- 7 个独立引擎 + harness/ 层，模块边界清晰

**遗留**：
- `agent_engine.py` 616 行，仍包含旧版 `_build_decompose_prompt`/`_llm_decompose` 死代码
- 前端 `index_original.html`（1204行）是 `index.html` 的 1:1 副本 — 冗余
- 前端 `app.js`（870行）存在但未被使用 — 未完成的迁移尝试残余
- 前端 `report_*.html` 为样本报告文件，不应存在于仓库

### 2.2 可靠性 6/10 🟡

**优点**：
- ParallelExecutor：3 次重试 + 30s 超时 + 失败降级
- DAG 拆解回退：LLM 失败时 fallback 到 registry 模板
- 异步锁保护 memory
- 优雅关闭（lifespan shutdown → flush）

**缺口**：
- ❌ SSE 端点无统一异常边界 — `run_pipeline` 内部异常会导致 SSE 流静默断开，前端无恢复机制
- ❌ LLM API 调用无重试 — `llm_client.py` 的 `chat()` 无 retry，单次网络波动直接抛异常
- ⚠️ 前端 `catch(e) {}` 4 处空 catch — 异常被静默吞掉（`index_original.html` 中）

### 2.3 可观测性 6/10 🟡

**优点**：
- `observability.py`：RequestTracker + TokenCounter + MetricsCollector
- `/api/metrics` 端点
- 启动自检（`startup_diag.py`）— 检测 .pyc 一致性、函数签名

**缺口**：
- ❌ 非结构化日志 — 当前是 `logging.info(f"...")` 自由文本，生产应改为结构化 JSON
- ❌ 无 trace ID 贯穿全链路 — `tracer.py` 只做时间戳，未传到 LLM 调用或工具调用
- ❌ 无告警机制 — 无错误率阈值、无 token 用量告警
- ⚠️ Token 计数是估算 — `est_tokens = len(prompt) // 2 + len(output) // 2`，中文实际约 1.5-2 字符/token

### 2.4 安全性 6/10 🟡

**优点**：
- Bearer Token 认证 + 滑窗 RateLimiter
- API Key 从 os.environ 读取，不进代码
- dev 模式（无 token 可运行）
- `_PUBLIC_PATHS` 保护非敏感端点

**缺口**：
- ❌ 无输入验证 — `POST /api/chat` 的 `message` 字段无长度限制、无 XSS 过滤；`session_id` 无格式校验
- ❌ SSE 端点无超时保护 — 长时间运行的请求无上限
- ⚠️ dev 默认 token 硬编码 — `zhijing-dev-token-2026` 写在 `auth.py` 里
- ⚠️ 无请求体大小限制

### 2.5 测试覆盖 6/10 🟡

**优点**：
- 93 backend + 14 frontend = 107 tests
- 全 mock（`conftest.py` mock OpenAI client），测试快速且隔离
- GitHub Actions 自动运行 pytest + ruff

**缺口**：
- ❌ 无覆盖率度量 — `pytest-cov` 未配置
- ❌ 无端到端集成测试 — 所有 LLM 调用被 mock
- ❌ `tools.py` 的 `_score_candidates` 有已知 `.format()` bug（2 个 xfail）
- ⚠️ `memory.py` 无并发测试 — 虽加锁但从未验证锁的增量

### 2.6 可部署性 7/10 🟢

**优点**：
- Dockerfile（30行）+ docker-compose.yml
- Docker HEALTHCHECK
- `.env` 分层（`.env` → `.env.{APP_ENV}` → os.environ）
- GitHub Actions CI
- `scripts/restart.sh` 洁净重启脚本

**缺口**：
- ⚠️ Dockerfile 缺 `pip install` 缓存 — 无 `--mount=type=cache`
- ⚠️ `requirements.txt` 使用范围约束而非精确版本锁定
- ⚠️ `pyproject.toml` 仅配了 ruff，无依赖声明

### 2.7 性能/扩展 7/10 🟢

**优点**：
- ParallelExecutor 真正并行（`asyncio.gather` + `return_exceptions`）
- SSE 流式响应
- 24h 报告缓存
- 模型分级（flash/pro/chat）降低 token 成本

**缺口**：
- ❌ 无连接池 — `llm_client.py` 为单例 `AsyncOpenAI`，高并发时可能成为瓶颈
- ⚠️ 单实例 — JSON 文件存储不支持多进程/多实例并发写
- ⚠️ 记忆压缩无并发控制 — 多 session 同时溢出时的压缩任务无保护

### 2.8 数据完整性 6/10 🟡

**优点**：
- `threading.Lock` + `asyncio.Lock` 双锁保护
- `_mark_dirty()` + `_flush()` 去重合并写入
- 启动时检测文件损坏

**缺口**：
- ❌ JSON 文件无备份 — 损坏/误删不可恢复
- ❌ 无 schema 版本化 — 记忆结构变更时旧数据无法自动迁移
- ⚠️ 无数据清理策略 — `data/memory_store.json` 会无限增长

---

## 三、具体问题清单

| # | 严重度 | 问题 | 涉及文件 | 状态 |
|---|---|---|---|---|
| P0-1 | 🔴 | llm_client.chat() 无重试 | llm_client.py | ✅ |
| P0-2 | 🔴 | SSE 端点无统一异常处理 | server.py | ✅ |
| P0-3 | 🟡 | Token 计数粗略估算（/2） | llm_client.py | 📋 |
| P1-1 | 🟡 | index_original.html 与 index.html 重复 | frontend/ | ✅ |
| P1-2 | 🟡 | app.js 870行未使用 | frontend/ | ✅ |
| P1-3 | 🟡 | report_*.html 样本报告在仓库 | frontend/ | ✅ |
| P1-4 | 🟡 | 旧版 _build_decompose_prompt/_llm_decompose 未删除 | agent_engine.py | ✅ |
| P1-5 | 🟡 | 前端空 catch(e) {} 仍有 4 处 | frontend/index.html | ✅ |
| P2-1 | 🟢 | 无结构化日志 | 全局 | ✅ |
| P2-2 | 🟢 | requirements.txt 无精确版本 | requirements.txt | 📋 |
| P2-3 | 🟢 | dev 默认 token 硬编码 | auth.py | 📋 |
| P2-4 | 🟢 | SSE 断线无前端重连 | frontend/ | ✅ |

---

## 四、生产就绪度矩阵

| 场景 | 就绪度 | 说明 |
|---|---|---|
| **内部团队 alpha** | ✅ 7/10 | 可直接用。107 项测试无回归，缓存和重试已就位 |
| **外部用户 beta** | ⚠️ 6/10 | 需先补：SSE 恢复、输入验证、LLM 重试 |
| **生产 SaaS** | ❌ 5/10 | 需多租户、结构化日志、监控告警、DB 迁移、压测 |

---

## 五、执行优先级

按投资回报比排序：

| 优先级 | 事项 | 约需 | 价值 |
|---|---|---|---|
| 1 | 前端死代码清理 | 30min | 消除维护混乱 |
| 2 | 后端死代码清理 | 30min | 减少混淆风险 |
| 3 | 前端空 catch 修复 | 15min | 可调试性 |
| 4 | llm_client 重试机制 | 1h | 可靠性直接提升 |
| 5 | SSE 异常处理 | 1h | 用户体验底线 |
| 6 | pytest-cov 覆盖率 | 30min | 测试可见性 |
| 7 | 结构化日志 + trace ID | 2h | 运维基础 |
| 8 | 输入验证 | 1h | 安全底线 |
