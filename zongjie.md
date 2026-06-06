# 织镜 ZHÌJÌNG — 从0到1全记录

> 服饰电商 AI Agent 产品 · 架构演进 · 优化里程碑

***

## 一、产品概述

**织镜 ZHÌJÌNG** 是一个面向服饰电商场景的 AI Agent 产品，支持以下 7 种意图：

| 意图      | 说明                      |
| ------- | ----------------------- |
| 单品选品分析  | 市场数据、价格带、趋势分析           |
| 多品牌竞品对标 | 双品牌对比 + SWOT 矩阵         |
| 品类趋势洞察  | 流行方向、面料趋势、热度排序          |
| 商品文案生成  | 淘宝/抖音/小红书多平台文案          |
| 定价策略分析  | 价格带分布、成本利润测算            |
| 上新排期优化  | 季节曲线、大促日历、测款节奏          |
| 文生图     | 豆包 Seedream 生成服装产品摄影/线稿 |

**技术栈**：Python 3.11 / FastAPI / SSE 流式 / DeepSeek LLM / 豆包 Seedream\
**搜索源**：博查 AI（中文）+ Tavily（英文）双源并行\
**部署**：Docker 单容器，21 个 Python 模块，3,400+ 行，831 行前端

***

## 二、架构演进史

### v1 — Demo 原型

```
server.py → agent_engine（单一 God Object 963行）
         → tools.py（硬编码规则提取）
         → llm_client.py（直连 DeepSeek）
         → memory.py（JSON 文件单写）
```

- 前端：单 HTML，对话区 + Console
- 无认证、无超时、无限流、同步 I/O

### v2-v8 — Harness 架构

- 引入 `harness/` 层：ToolRegistry / DAGLoader / ParallelExecutor / CostRouter / TraceCollector
- 双源搜索（博查 ∥ Tavily）
- 反思修正闭环（7分阈值，最多2次重试）
- 工作记忆增强 + 多轮对话
- 文生图集成（豆包 Seedream 5.0）
- 前端报告可视化组件（rc-\* CSS 体系）

### 架构优化四阶段

#### Phase 1：硬加固（不改架构，加保护层）

| 新增文件              | 功能                                       |
| ----------------- | ---------------------------------------- |
| `backend/auth.py` | Bearer Token 认证中间件 + 滑窗 RateLimiter      |
| `memory.py` 改造    | +threading.Lock + mark\_dirty/flush 异步写入 |
| `server.py` 改造    | +lifespan shutdown hook                  |

- P0 认证 ✅ / P0 异步 I/O ✅ / P0 并发锁 ✅ / P0 优雅关闭 ✅

#### Phase 2：提取核心（拆 God Object）

| 新增文件                         | 提取自 agent\_engine          |
| ---------------------------- | -------------------------- |
| `backend/intent.py`          | 意图识别 + 路由（IntentRouter）    |
| `backend/report.py`          | 报告生成 + 6套模板（ReportBuilder） |
| `backend/reflect.py`         | 质量反思（ReflectionEngine）     |
| `backend/image_optimizer.py` | 文生图 prompt 优化              |
| `backend/precheck.py`        | 前置校验 + 澄清交互                |

- agent\_engine 核心逻辑委托给 6 个独立引擎，run\_pipeline() 瘦身为纯编排层
- 所有模块独立可测

#### Phase 3：基础设施

| 新增/改造                      | 功能                                           |
| -------------------------- | -------------------------------------------- |
| `Dockerfile`               | 生产容器 + 健康检查                                  |
| `backend/observability.py` | RequestTracker + TokenCounter + /api/metrics |
| `server.py` 改造             | is\_disconnected() 请求取消 + time 追踪            |
| `llm_client.py` 改造         | chat()/chat\_sync() 中 record\_tokens()       |
| `executor.py` 改造           | asyncio.wait\_for 30s 超时保护                   |
| `conversation.py` 改造       | 关键词 15→40+ 扩展                                |
| `config.py` 改造             | APP\_ENV 分层 (.env / .env.dev / .env.prod)    |

#### Phase 4：多租户就绪 + 报告渲染加固

| 改造                           | 功能                                         |
| ---------------------------- | ------------------------------------------ |
| `agent_engine.py` DI 容器      | 6 个模块级全局单例 → __init__ 实例变量                 |
| `report.py` 模板重写             | 每套模板含精确 HTML 结构示例 + 10 条铁律                 |
| `index.html` fixReportLayout | 3 步 → 7 步（SWOT 修复/样式清理/裸表包裹/insight 修复）    |
| CSS 加固                       | +rc-swot-grid 兜底、+hover、+rc-table-fallback |

#### 渲染问题专项修复

| 问题          | 根因                                          | 修复                                                                   |
| ----------- | ------------------------------------------- | -------------------------------------------------------------------- |
| SWOT 纯文本堆砌  | LLM 自创 rc-swot-grid/rc-swot-item 类名，CSS 不匹配 | 三层修复：① Prompt 注入精确 HTML ② CSS 兜底 ③ JS 运行时转换                          |
| 竞品对比无卡片     | LLM 未使用 rc-brand-card                       | 模板含 `<div class="rc-compare"><div class="rc-brand-card brand-a">` 示例 |
| insight 无强调 | 缺失 `<strong>` 标签                            | JS 自动提取首行文本包裹                                                        |

***

## 三、项目文件清单

```
fashion-agent-v2/
├── Dockerfile                          # 生产容器
├── setup_env.sh                        # 密钥迁移脚本
├── test_regression.sh                  # 自动化回归测试（7意图+限流+指标）
├── .env.example / .env.prod            # 配置模板
├── docs/
│   ├── ARCHITECTURE_V2.md              # v2 架构设计
│   └── ARCHITECTURE_OPTIMIZATION.md    # 四阶段优化方案
├── data/
│   └── memory_store.json               # 会话持久化（JSON）
├── frontend/
│   └── index.html                      # 单页应用（对话区+Console+状态管理）
└── backend/
    ├── server.py                       # FastAPI 主入口（6个API端点）
    ├── config.py                       # 统一配置（APP_ENV分层）
    ├── auth.py                         # 认证+速率限制中间件
    ├── observability.py                # 指标+Token追踪
    ├── agent_engine.py                 # 编排引擎（DI容器，~400行编排逻辑）
    ├── intent.py                       # 意图识别引擎
    ├── precheck.py                     # 前置校验引擎
    ├── report.py                       # 报告生成器+6套模板
    ├── reflect.py                      # 质量反思引擎
    ├── image_optimizer.py              # 文生图prompt优化
    ├── llm_client.py                   # DeepSeek/豆包 API 客户端
    ├── tools.py                        # 工具层（搜索+LLM提取+文生图）
    ├── memory.py                       # 记忆系统（五层架构+异步+锁）
    ├── conversation.py                 # 多轮对话检测
    └── harness/                        # 管道基础设施
        ├── registry.py                 # 工具注册中心
        ├── dag_loader.py               # DAG模板加载
        ├── executor.py                 # 并行执行器（30s超时）
        ├── router.py                   # 查询复杂度路由
        └── tracer.py                   # 全链路追踪
```

***

## 四、技术架构全景

```
                        ┌──────────────┐
                        │  FastAPI App │
                        │  server.py   │
                        └──────┬───────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
   ┌──────▼──────┐   ┌────────▼────────┐   ┌───────▼───────┐
   │AuthMiddleware│   │ /api/metrics    │   │ SSE /api/chat │
   │+RateLimiter  │   │ observability   │   │ +req_tracker  │
   └──────────────┘   └─────────────────┘   └───────┬───────┘
                                                     │
                                          ┌──────────▼──────────┐
                                          │    AgentEngine      │
                                          │  (编排层, DI容器)   │
                                          └──────────┬──────────┘
                                                     │
    ┌────────┬────────┬────────┬─────────┬───────────┼──────────┬────────┐
    │        │        │        │         │           │          │        │
┌───▼──┐ ┌──▼───┐ ┌──▼───┐ ┌─▼────┐ ┌──▼───┐ ┌────▼────┐ ┌───▼───┐ ┌──▼────┐
│Intent│ │Pre   │ │Report│ │Reflect│ │Image │ │Memory   │ │Harness│ │Config │
│Router│ │check │ │Build │ │Engine │ │Optim │ │System   │ │Layer  │ │Layer  │
│      │ │Engine│ │er    │ │      │ │izer  │ │+Lock    │ │+TO    │ │APP_ENV│
└──────┘ └──────┘ └──────┘ └──────┘ └──────┘ │+AsyncIO │ │Registry│ └───────┘
                                             │+Flush   │ │DAGLoad │
                                             └────┬────┘ │Executr │
                                                  │      │Router  │
                                            ┌─────▼─────┐│Tracer  │
                                            │ JSON File  │└────────┘
                                            │ 持久化      │
                                            └───────────┘
```

### 数据流

```
用户输入 → IntentRouter（意图识别）
         → PrecheckEngine（信息校验）
         → DAG拆解（deepseek-v4-pro）
         → 并行执行：
             博查搜索 ∥ Tavily搜索
             → LLM趋势提取 ∥ LLM价格分析 ∥ LLM竞品分析
             → LLM综合评分
         → ReportBuilder（报告生成，deepseek-chat）
         → ReflectionEngine（质量审查，阈值7分，最多2次重试）
         → 记忆持久化 + Token追踪
         → SSE 流式返回
```

***

## 五、关键 API 端点

| 端点                              | 方法   |  认证 | 说明                           |
| ------------------------------- | ---- | :-: | ---------------------------- |
| `/`                             | GET  |  ❌  | 前端页面                         |
| `/api/health`                   | GET  |  ❌  | 健康检查（含 auth/env/sessions 状态） |
| `/api/chat`                     | POST |  ✅  | SSE 流式对话（核心接口）               |
| `/api/metrics`                  | GET  |  ❌  | 请求量/延迟P50-P99/Token用量        |
| `/api/memory/{id}`              | GET  |  ❌  | 会话记忆状态                       |
| `/api/memory/{id}/conversation` | GET  |  ❌  | 会话历史                         |

***

## 六、关键决策记录

| 决策                                 | 原因                      |
| ---------------------------------- | ----------------------- |
| DeepSeek 直连（非 OpenRouter）          | 降低延迟，中文优化好              |
| deepseek-chat 主力 + v4-pro 仅 DAG 拆解 | 降成本 90%，v4-pro 仅需深度推理环节 |
| 博查 + Tavily 双源并行                   | 博查覆盖中文电商，Tavily 覆盖国际数据  |
| 反思闭环（7分阈值，2次重试）                    | 保证报告质量，控制 token 消耗      |
| 文生图默认真实摄影                          | 避免卡通/插画式输出，符合电商场景       |
| JSON 文件持久化（非 SQLite）               | 当前规模（\~130会话）不需要关系型数据库  |
| DI 容器而非全局单例                        | 为未来多租户隔离做准备             |
| SSE 流式返回                           | 实时进度反馈，支持请求取消           |

***

## 七、生产部署

```bash
# 构建
docker build -t zhijing .

# 运行
docker run -p 8899:8899 \
  -e APP_ENV=production \
  -e API_TOKEN=*** \
  -e DEEPSEEK_API_KEY=*** \
  -e BOCHA_API_KEY=*** \
  -e TAVILY_API_KEY=*** \
  -e ARK_API_KEY=*** \
  zhijing
```

**前置条件**：

1. 设置 `API_TOKEN` 环境变量（否则无法访问）
2. 配置反向代理（Nginx/Caddy）加 HTTPS
3. 可选：挂载 `data/` 目录持久化会话数据

***

## 八、当前架构评分

| 维度    |   评分  | 说明                      |
| ----- | :---: | ----------------------- |
| 健壮性   |  ⭐⭐⭐⭐ | P0 全清零，认证/超时/限流/优雅关闭就位  |
| 可维护性  | ⭐⭐⭐⭐½ | 6 引擎独立 + DI 容器 + 模块边界清晰 |
| 灵活性   |  ⭐⭐⭐⭐ | 新增意图/工具成本低，报告模板可独立配置    |
| 生产就绪度 |  ⭐⭐⭐⭐ | 可单租户生产部署，SaaS 多租户需额外存储层 |

***

*最后更新：2026-06-05*
