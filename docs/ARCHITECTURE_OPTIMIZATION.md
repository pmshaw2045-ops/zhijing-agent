# 织镜 ZHÌJÌNG 架构优化方案

> 原则：增量演进、功能不变、每步可回滚  
> 策略：绞杀者模式（Strangler Fig）——新模块包围旧核心，逐步替换

---

## 总体路线

```
Phase 1 (硬加固)     Phase 2 (提取核心)    Phase 3 (基础设施)    Phase 4 (多租户)
    ✅ 已全部完成         ✅ 已全部完成         ✅ 已基本完成          ⚠️ 部分完成
   1-2 天                3-5 天                5-7 天                 7-10 天
   不改架构              拆 god object          存储/部署/监控          SaaS 就绪
```

每 Phase 独立上线，不影响正在运行的功能。

> **当前状态(2026-06-08)**：
> - Phase 1-2 全部完成 ✅
> - Phase 3 除 SQLite 外已完成（Dockerfile有但无docker-compose）
> - Phase 4 仅配置分层完成，DI容器未实现

---

## Phase 1：硬加固（不改架构，加保护层）

**目标**：消除 P0 阻断项，不碰 agent_engine 核心逻辑。

### 1.1 API 认证（1h）

```
新增文件: backend/auth.py
修改文件: backend/server.py（+5行）
```

**策略**：Bearer Token 中间件，默认启用但提供 dev 模式。

```python
# backend/auth.py — FastAPI 中间件
# 1. 检查 Authorization: Bearer <token>
# 2. 从 config.API_TOKEN 读取（默认值用于dev）
# 3. 无 token 返回 401
```

**不改现有代码**：只在 `server.py` 加一行 `app.add_middleware(AuthMiddleware)` + 一个环境变量 `API_TOKEN`。所有现有 API 路径继承认证。

**验证**：`curl localhost:8899/api/chat` → 401；`curl -H "Authorization: Bearer xxx"` → 200。

### 1.2 异步文件写入（30min）

```
修改文件: backend/memory.py
```

**策略**：包装 `_save()` 为异步，用 `asyncio.to_thread` 把 JSON 写入放到线程池。

```python
# 新增后台写入任务
self._dirty = False
self._save_task = None

def _mark_dirty(self):
    self._dirty = True

async def _flush(self):
    if self._dirty:
        await asyncio.to_thread(self._do_save)
        self._dirty = False
```

不改 `_save()` 的调用方。每个 `_save()` 调用改为 `_mark_dirty()`，AgentEngine 在 Pipeline 结束时调用一次 `await memory._flush()`。

**风险**：极低。写入逻辑不变，只是去重合并 + 异步化。

### 1.3 内存锁保护（20min）

```
修改文件: backend/memory.py
```

**策略**：`asyncio.Lock` 保护 `_store` 读写。

```python
self._lock = asyncio.Lock()

async def get_conversation(self, session_id):
    async with self._lock:
        return self._store["sessions"].get(session_id, {}).get("conversation", [])
```

现有代码是同步方法，改为 async 需改调用链。**最小改动方案**：给 `_store` 操作加 `threading.Lock`（同步锁），不改方法签名。

**风险**：极低。

### 1.4 优雅关闭（15min）

```
修改文件: backend/server.py
```

**策略**：在 lifespan 中注册 shutdown handler。

```python
@asynccontextmanager
async def lifespan(app):
    yield  # startup
    # shutdown
    engine.memory._save()
    logger.info("Memory flushed, shutting down")
```

**风险**：无。

### Phase 1 验证清单

- [x] `curl /api/chat` 无 token → 401
- [x] `curl /api/chat` with token → 200, SSE 正常
- [x] 并发 5 请求 → 无数据错乱
- [x] `Ctrl+C` 关闭 → 日志显示 Memory flushed

> ✅ 全部通过（2026-06-06）

---

## Phase 2：提取核心（拆 God Object）

**目标**：agent_engine.py 从 963 行降到 ~400 行。每个提取的模块独立可测。

**实际**：agent_engine.py 当前 616 行（未达 400 目标，但拆出了 7 个引擎 + 1 个共享函数）。

**核心策略**：提取而非重写。每个 Phase 2.x 独立可上线。

**Phase 2 额外提取**（设计方案之外的增量）：
- 🔄 `DecomposeEngine` → `backend/decompose_engine.py`（从 `_llm_decompose` / `_build_decompose_prompt` 提取）
- 🔄 `goal_to_text()` → `backend/intent.py`（从 `decompose_engine._goal_to_text` 提升为共享函数）
- 🔄 `conversation_manager` → `backend/conversation.py`（多轮对话提取）
- 🔄 `DAG_TEMPLATES` / `REPORT_TEMPLATES` → 部分移至 `intent_registry.py`

### 2.1 提取 IntentRouter（1h）

```
新增: backend/intent.py（~150行）
删减: agent_engine.py（-180行）
```

**转移内容**：
- `_llm_intent` + `_build_intent_prompt`
- `_fallback_intent`
- `_normalize_intent`
- `_route_by_intent`
- `_build_memory_context`

**新类**：`IntentRouter`
```python
class IntentRouter:
    async def classify(self, user_input, mode, session_id, memory) -> IntentResult
```

**agent_engine 调用变化**：
```python
# 旧: intent = await self._llm_intent(user_input, mode, session_id)
# 新: intent = await self.intent_router.classify(user_input, mode, session_id, self.memory)
```

**风险控制**：Phase 2.1 提取后用现有 curl 测试用例全量回归。不改 Pipeline 流程，只换实现位置。

### 2.2 提取 ReportBuilder（1h）

```
新增: backend/report.py（~120行）
删减: agent_engine.py（-150行）
```

**转移内容**：
- `_llm_report` + `_build_report_prompt`
- `_build_report_memory_context`
- `REPORT_TEMPLATES`（移到 report.py 顶部）
- `_clean`

**新类**：`ReportBuilder`
```python
class ReportBuilder:
    REPORT_TEMPLATES = {...}  # 从 agent_engine 移过来
    async def generate(self, intent, mode, exec_results, session_id, memory, 
                       improvement_instructions="") -> str
```

**风险控制**：报告模板内容一字不改，只是搬家。

### 2.3 提取 ReflectionEngine（30min）

```
新增: backend/reflect.py（~80行）
删减: agent_engine.py（-60行）
```

**转移内容**：`_llm_reflect` + `_build_reflect_prompt`

### 2.4 提取 PrecheckEngine（20min）

```
新增: backend/precheck.py（~70行）
删减: agent_engine.py（-50行）
```

**转移内容**：`_phase_precheck` + `_build_clarify_message`

### 2.5 提取 ImageOptimizer（15min）

```
新增: backend/image_optimizer.py（~60行）
删减: agent_engine.py（-40行）
```

### Phase 2 后 agent_engine.py 结构

```
class AgentEngine:                    # ~350行（原963行）
    def __init__(self):
        self.intent_router = IntentRouter()
        self.report_builder = ReportBuilder()
        self.reflection_engine = ReflectionEngine()
        self.precheck = PrecheckEngine()
        self.image_optimizer = ImageOptimizer()
        self.memory = MemorySystem()

    async def run_pipeline(...):      # ~180行（Pipeline 编排逻辑）
        # Phase 0: conversation
        # Phase 1: self.intent_router.classify()
        # Phase 2: self.precheck.check()
        # Phase 3: (decompose or image)
        # Phase 4-5: executor
        # Phase 6: self.report_builder.generate()
        # Phase 7: self.reflection_engine.evaluate()
```

### Phase 2 验证清单

- [x] 全部 curl 测试用例（selection/competitive/trend/copy/pricing/launch/image）通过
- [x] 报告内容与优化前基本一致
- [x] pytest 93 passed + 2 xfailed
- [x] agent_engine.py 616 行（目标 400，因新增 decompose_engine 和 conversation 等独立模块仍留了一定编排逻辑）

---

## Phase 3：基础设施（生产级底座）

### 3.1 存储层升级（2h）

```
| 新增: backend/store.py（抽象接口，已实现 ✅）
| 新增: backend/store_json.py（已实现 ✅，当前默认后端）
| 新增: backend/store_sqlite.py（📋 未实现 — 当前 ~360 会话用 JSON 文件足够）
```

**策略**：定义 `Store` 抽象基类，MemorySystem 依赖注入。

```python
class Store(ABC):
    async def load(self) -> dict: ...
    async def save(self, data: dict): ...

class JsonFileStore(Store):  # 当前实现，保留
    ...

class SQLiteStore(Store):    # 生产级，事务+并发安全
    ...
```

**迁移路径**：
1. 创建 Store 接口 → MemorySystem 内部适配
2. 默认使用 JsonFileStore（当前行为不变）
3. 通过环境变量 `STORE_BACKEND=sqlite` 切换到 SQLite
4. 提供迁移脚本 `python -m backend.migrate_store`

### 3.2 可观测性（1.5h）

```
新增: backend/observability.py
修改: backend/server.py（+3行）
```

**内容**：
- 结构化日志（`structlog`）：每条日志带 `request_id`、`session_id`、`phase`
- 请求耗时统计（middleware）：`/api/chat` 的 P50/P95/P99
- LLM token 用量累计（全局计数器，暴露到 `/api/metrics`）
- 错误率监控（5xx 比例）

不引入 Prometheus/Grafana 等重依赖。用 `structlog` + 简单的 `/api/metrics` 端点。

### 3.3 Docker 化（1h）

```
新增: Dockerfile （✅ 已实现）
新增: docker-compose.yml （📋 未实现 — 当前单容器手动启动即可）
```

单容器部署，包含 uvicorn + 前端静态文件。健康检查 + 优雅关闭。

### 3.4 请求取消（30min）

```
修改: backend/server.py
```

FastAPI 原生支持 `request.is_disconnected`。在 SSE generator 中检测：

```python
async def generate():
    async for event in engine.run_pipeline(...):
        if await request.is_disconnected():
            engine.cancel(session_id)  # 通知 engine 停止
            break
        yield ...
```

---

## Phase 4：多租户就绪

### 4.1 依赖注入容器（2h）

> 📋 未实现。当前 agent_engine 在 `__init__` 中直接创建实例变量（`self.memory = MemorySystem()` 等），未使用 DI 容器。待多租户场景到来时再实施。

```
计划新增: backend/container.py（尚未创建）
```

用简单的 DI 容器替代全局单例。

```python
class Container:
    def __init__(self, config: Config):
        self.store = create_store(config.store_backend)
        self.memory = MemorySystem(self.store)
        self.intent_router = IntentRouter()
        # ...
    
    def create_engine(self, tenant_id: str) -> AgentEngine:
        # 每个租户独立实例
        return AgentEngine(
            memory=MemorySystem(self.store, namespace=tenant_id),
            ...
        )
```

不强制替换全局单例。Phase 4.1 先建容器 + 工厂方法，Phase 4.2 逐步迁移调用方。

### 4.2 配置分层（30min）

```
backend/config.py → 支持 dev / staging / prod 分层
.env.dev / .env.staging / .env.prod
```

通过 `APP_ENV` 环境变量切换。

---

## 风险控制总则

| 原则 | 操作 |
|------|------|
| 每次改动 ≤ 2 个文件 | 大规模重构拆成多个小 PR |
| 新模块与旧模块并存 | 先加新的，验证后再删旧的 |
| 每 Phase 有回滚路径 | Git tag 标记 Phase 前状态 |
| CI 自动化回归 | Phase 1 就开始建 curl 测试脚本 |
| 不改 API 契约 | `/api/chat` 的请求/响应格式一直不变 |

## 不做什么

- ❌ 不引入 Web 框架（保持 FastAPI）
- ❌ 不改 SSE 协议（前后端接口稳定）
- ❌ 不重写前端（仅在当前 HTML 文件内优化）
- ❌ 不引入 Celery/RabbitMQ 等消息队列（不需要异步任务解耦）
- ❌ 不引入微服务拆分（单进程足够）
