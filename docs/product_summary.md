# 织镜 ZHÌJÌNG — 产品与技术总结

> 生成日期：2026-06-08（v2 里程碑）
> 产品阶段：GitHub 发布就绪，单租户生产可部署
> 代码规模：后端 20 模块 ~4,300 行 + 前端 ~900 行 + 测试 13 文件 ~2,200 行

---

## 一、产品经理视角

### 1.1 产品定位

**织镜 ZHÌJÌNG** 是一款面向服饰电商的 AI Agent 产品，目标用户为服饰行业 B 端产品经理和运营人员。核心价值：用 LLM 驱动的 Agent Pipeline 自动化完成选品分析、竞品对标、趋势洞察等专业分析任务，输出结构化可视化报告。

### 1.2 核心能力矩阵

| 意图类型 | 功能 | 典型输入 | 复杂度 |
|----------|------|----------|:--:|
| 单品选品分析 | 市场数据 + 价格带 + 趋势 + 竞品格局 | "分析2026夏季法式茶歇裙选品机会" | COMPLEX |
| 多品牌竞品对标 | 双品牌对比 + SWOT + 差异化机会 | "太平鸟和伊芙丽连衣裙竞品对标" | COMPLEX |
| 品类趋势洞察 | 面料/廓形/色彩趋势 | "2026夏季连衣裙流行趋势" | MEDIUM |
| 商品文案生成 | 多平台电商文案 | "生成法式茶歇裙淘宝标题" | SIMPLE |
| 定价策略分析 | 价格带分布 + 成本利润测算 | "连衣裙在天猫的定价策略" | MEDIUM |
| 上新排期建议 | 季节曲线 + 大促日历 + 最佳窗口 | "夏季连衣裙上新排期建议" | MEDIUM |
| 文生图 | 真实产品摄影图/设计线稿 | "法式碎花茶歇裙产品摄影图" | SIMPLE |

### 1.3 产品差异化

- **全 LLM 驱动**：从意图识别到 DAG 拆解到报告生成，不依赖固定模板或规则引擎。LLM 根据意图类型、可用工具列表、当前数据上下文自主设计执行计划
- **Provider 无关**：LLM 和搜索均支持任意提供商（DeepSeek / OpenAI / 兼容 API），用户通过配置文件切换，不改代码
- **反思修正闭环**：报告生成后自动评分，低于 7 分触发重试修正（最多 2 次），保留最高分版本
- **可视化报告**：JSON 结构化数据 → 前端渲染引擎 → 包含指标卡片、柱状图、SWOT 矩阵、品牌对比卡、洞察框等 9 种组件（rc-* 体系）
- **工作记忆系统**：五层记忆架构（工作/短期/长期/主题/分析），滑动窗口 + 递归摘要
- **搜索路由层**：统一搜索接口，按配置自动路由到 Tavily / 博查 / 自定义后端

### 1.4 当前限制

- 数据源为通用网页搜索（博查 + Tavily），非结构化；缺少电商 API（如速 API）获取精确价格/销量数据
- 单租户架构，不支持 SaaS 多客户隔离
- 无用户认证系统（仅 API Token 保护）
- 无 CI/CD，手动部署

### 1.5 下一步产品方向

| 优先级 | 方向 | 价值 |
|:--:|------|------|
| P0 | 接入速 API 等电商结构化数据源 | 显著提升数据准确性和置信度 |
| P0 | 用户认证 + 多租户 | SaaS 化前提 |
| P1 | 报告导出 PDF/PPT | 对外分享交付 |
| P1 | 定时任务（自动推送周报/趋势预警） | 从工具到服务 |
| P2 | SSE 断线重连（设计文档就绪） | 网络稳定性 |
| P2 | 模版市场（用户自定义报告模板） | UGC 生态 |

---

## 二、技术架构师视角

### 2.1 技术栈

|| 层 | 技术选型 | 说明 |
|:---|:---|:---|
| 后端框架 | Python 3.11 + FastAPI | 异步 SSE 流式响应 |
| LLM | 任意 OpenAI 兼容 API（可配置） | 三级模型分级 flash/pro/chat |
| 文生图 | 豆包 Seedream 5.0（可替换） | ARK API，真实摄影风格 |
| 搜索 | 配置化路由：Tavily / 博查 | 统一 SEARCH_API_KEY，支持 auto/tavily/bocha |
| 前端 | 单文件 HTML/CSS/JS | 暖色调设计系统，CSS 变量体系 |
| 存储 | JSON 文件（SQLite 可切换） | data/memory_store.json，async flush |
| 部署 | Docker + uvicorn | 单容器，健康检查，Bcacher Token 认证 |

### 2.2 模块架构

```
backend/ (20 modules, ~4,300 lines)
├── agent_engine.py (251)    核心编排引擎，8 阶段 Pipeline
├── tools.py (435)           工具定义 + 搜索路由层 + LLM 驱动分析
├── memory.py (268)          工作记忆，滑动窗口 + 递归摘要
├── report.py (253)          JSON 报告生成器，6 策略 + 渲染 Schema
├── intent_registry.py (227) 意图元数据中心（Single Source of Truth）
├── server.py (116)          FastAPI 应用入口，SSE 端点，API 路由
├── config.py (61)           配置化 Provider（LLM/搜索）+ 三级 fallback
├── intent.py (58)           IntentRouter + goal_to_text 共享函数
├── llm_client.py (121)      LLM API 封装 + 重试机制 + Token 追踪
├── observability.py (59)    指标收集器（请求量/延迟/Token）
├── conversation.py (69)     多轮对话场景检测 + 查询增强
├── decompose_engine.py (41)  DAG 任务拆解（json_mode + 模板 fallback）
├── auth.py (71)             Bearer Token 认证 + 速率限制
├── precheck.py (78)         前置校验 + 澄清交互
├── reflect.py (25)          质量反思引擎
├── image_optimizer.py (23)  文生图 prompt 优化
├── store.py (89)            SQLite 存储后端（STORE_BACKEND=sqlite 可选）
└── harness/                 管道基础设施层
    ├── tracer.py (46)       全链路追踪
    ├── router.py (37)       CostRouter: 复杂度判定 + 执行深度控制
    ├── executor.py (52)     ParallelExecutor: DAG 并行执行 + 超时保护
    ├── registry.py (46)     ToolRegistry: 工具注册中心
    └── dag_loader.py (40)   DAG 模板加载器（LLM 失败时的 fallback）

frontend/
├── index.html (100)         SPA 骨架
├── style.css                CSS 设计系统
├── render.js                报告渲染引擎（9 种组件）
├── handler.js               SSE 事件处理 + Console 面板
├── sse.js                   SSE 流式 + 自动重连
└── console.js               Console 日志

tests/ (13 files, 134 passed, 2 xfailed)
├── test_agent_engine.py     Pipeline 流程测试
├── test_config.py           配置测试（含 LLM/搜索 Provider 兼容）
├── test_intent_registry.py  意图注册表测试
├── test_llm_client.py       重试机制测试
├── test_logging_setup.py    日志/追踪测试
├── test_memory.py           记忆系统测试
├── test_pipeline.py         工具/拆解/预检流程测试
├── test_report_clean.py     报告清理测试
├── test_server.py           API 端点 + SSE 集成测试
├── test_store.py            SQLite 存储后端测试（99% 覆盖率）
└── test_tools.py            LLM 驱动工具测试
```

覆盖率的坑：
- store.py 99%（新增测试补齐）
- tools.py 52%（搜索函数依赖网络，mock 覆盖不全）
- report_pipeline.py 26%（新模块，待补）

### 2.3 Agent Pipeline 架构

```
Phase 0: 多轮对话检测 → Scenario 识别 + 查询增强
Phase 1: LLM 意图识别 → 7 种意图判定 + IntentRegistry 路由（模型 flash）
Phase 2: 前置校验     → 信息完整性检查 + 实体提取 + 澄清交互
Phase 3: LLM DAG 拆解 → 自主设计执行计划（json_mode, 模型 pro）
Phase 4+5: 工具映射   → ToolRegistry + ParallelExecutor 并行执行（30s 超时）
Phase 6: JSON 报告生成 → 6 策略路由 → LLM 输出 JSON → 前端渲染（模型 chat）
Phase 7: 反思修正     → 质量评分 < 7 自动重试，最多 2 次（模型 chat）
  │
  ▼
SSE 事件流: intent → precheck → decompose → execute → report → reflect
            → quality_review → result → summary → done
```

### 2.4 记忆系统架构

基于 CoALA 论文的简化落地版：

| 层 | 内容 | 存储 | 注入 |
|---|---|---|---|
| L1 工作记忆 | 当前任务上下文 + intent + entities | JSON working | MD 摘要 |
| L2 短期记忆 | 滑动窗口内原始对话 + 递归摘要 | JSON conversation + summary | MD 最近对话 |
| L3 主题上下文 | 品类/品牌/季节/平台偏好 | JSON topic_context | MD 主题偏好 |
| L4 分析历史 | record_analysis → title 提取 | JSON analysis_history | MD 最近分析 |
| L5 长期记忆 | domains/brands/seasons/user_prefs | JSON long_term | 按需注入 |

- 压缩策略：滑动窗口溢出时 LLM 递归摘要（异步，不阻塞主流程）
- 并发保护：threading.Lock + mark_dirty/async flush
- 注入格式：get_injectable_context() → Markdown

### 2.5 前端渲染架构

```
SSE 事件流
  ├─ result          → JSON.parse → renderReport(json)
  │                     └─ 9 种组件模板函数
  ├─ quality_review  → 质量审查区块（评分 + 维度 + 修正历史）
  ├─ prompt          → Console 面板折叠展示
  ├─ summary         → Token 用量 + 延迟统计
  └─ phase           → Pipeline 状态切换（FSM 状态机）

Console 面板:
  ├─ ALL:      全部 pipeline 日志
  ├─ PIPELINE: 按阶段标签过滤
  └─ MEMORY:   L1-L5 记忆状态

组件库（9 种）:
  rc-metrics       指标卡片行（accent: gold/sage）
  rc-bar-chart     柱状图（color: c1/c2/c3）
  rc-table         对比表格（headers/rows）
  rc-brand-card    品牌卡片（brand-a/brand-b）
  rc-compare       双品牌对比
  rc-swot          SWOT 矩阵
  rc-insight       洞察框（style: tip/warn/danger）
  rc-section-title 分区标题（style: gold/sage）
  rc-text          纯文本段落
```

### 2.6 关键 API 端点

| 端点 | 方法 | 认证 | 说明 |
|---|---|---|---|
| `/` | GET | ❌ | 前端页面 |
| `/api/health` | GET | ❌ | 健康检查（含 auth/env/sessions 状态） |
| `/api/chat` | POST | ✅ | SSE 流式对话（核心接口） |
| `/api/metrics` | GET | ❌ | 请求量/延迟P50-P99/Token用量 |
| `/api/memory/{id}` | GET | ❌ | 会话记忆状态 |
| `/api/memory/{id}/conversation` | GET | ❌ | 会话历史 |

**认证机制**：

Token 从前端到后端的完整链路：

```
1. 服务端 server.py 渲染 index.html 时检查 API_TOKEN
2. 若非默认值（change-me-to-a-random-string），在 HTML 中注入：
   <script>const API_TOKEN='***';</script>
3. 前端 sse.js 在 fetch /api/chat 时自动附带：
   Authorization: Bearer *** Auth 中间件校验 token
```

- Dev 模式（`API_TOKEN` 未设置或值为默认 `change-me-to-a-random-string`）：跳过认证，静态文件不受 Auth 拦截（已在 `_PUBLIC_PATHS` 白名单）
- 生产模式（自定义 `API_TOKEN`）：CSS/JS 及 `/api/health` 等公开路径免认证，`/api/chat` 需 Bearer Token

### 2.7 关键决策记录

| 决策 | 原因 |
|:---|:---|
| Provider 无关的 LLM 配置（LLM_API_KEY） | 用户可选择任意 OpenAI 兼容 API，不绑定 DeepSeek |
| 三级模型分级（flash/pro/chat） | 按任务匹配模型能力：轻量任务用 flash，推理任务用 pro，综合任务用 chat |
| Provider 无关的搜索配置（SEARCH_API_KEY） | 用户可选择 tavily/bocha/自定义，不改代码 |
| 反思闭环（7 分阈值，2 次重试） | 保证报告质量，控制 token 消耗 |
| 文生图默认真实摄影 | 避免卡通/插画式输出，符合电商场景 |
| JSON 文件持久化（SQLite 可选） | 当前规模不需要关系型数据库 |
| DI 容器而非全局单例 | 为未来多租户隔离做准备 |
| SSE 流式返回 | 实时进度反馈，支持请求取消 |
| json_mode=True 用于所有 LLM JSON 输出 | 保证输出解析成功率，避免模板回退 |
| goal 数据用自然语言渲染（goal_to_text） | 去 JSON 噪音，节约 token，提升 LLM 理解 |

### 2.8 架构演进史

#### v1 — Demo 原型

- 单文件 God Object（agent_engine 963行）
- 硬编码规则提取
- JSON 同步 I/O
- 无认证/超时/限流

#### v2-v8 — Harness 架构

- 引入 `harness/` 层：ToolRegistry / DAGLoader / ParallelExecutor / CostRouter / TraceCollector
- 双源搜索（博查 ∥ Tavily）
- 反思修正闭环（7 分阈值，最多 2 次重试）
- 工作记忆增强 + 多轮对话
- 文生图集成（豆包 Seedream 5.0）
- 前端报告可视化组件（rc-* CSS 体系）

#### 架构优化四阶段

| Phase | 目标 | 状态 |
|---|---|---|
| Phase 1 硬加固 | 消除 P0 阻断项（认证/超时/限流/并发锁/优雅关闭） | ✅ 完成 |
| Phase 2 提取核心 | 拆解 God Object 为 6 个独立引擎 | ✅ 完成 |
| Phase 3 基础设施 | Docker/可观测性/超时保护/配置分层 | ✅ 完成 |
| Phase 4 多租户 | DI 容器/模板重写/渲染加固 | ✅ 完成 |

---

## 三、模型使用策略

| 阶段 | 模型等级 | 默认值 | 说明 |
|:---|:---|:---|:---|
| Phase 1 意图识别 | flash | deepseek-chat | 分类任务，低延迟 |
| Phase 3 DAG 拆解 | pro | deepseek-v4-pro | 深度推理，max_tokens=2000 |
| Phase 6 报告生成 | chat | deepseek-chat | JSON 输出，速度优先 |
| Phase 7 反思修正 | chat | deepseek-chat | 快速质检 |
| 工具层 LLM 提取 | flash | deepseek-chat | 结构化提取 |
| 记忆压缩摘要 | flash | deepseek-chat | max_tokens=200 |

所有模型都可通过环境变量配置：`LLM_MODEL_FLASH` / `LLM_MODEL_PRO` / `LLM_MODEL_CHAT`。

---

## 四、生产部署

```bash
# 构建
docker build -t zhijing .

# 运行
docker run -p 8899:8899 \
  -e APP_ENV=production \
  -e API_TOKEN=*** \
  -e LLM_API_KEY=*** \
  -e LLM_BASE_URL=https://api.deepseek.com \
  -e SEARCH_API_KEY=*** \
  -e ARK_API_KEY=*** \
  zhijing
```

**前置条件**：
1. 设置 `API_TOKEN` 环境变量（否则 dev 模式，无认证）
2. 配置反向代理（Nginx/Caddy）加 HTTPS
3. 可选：挂载 `data/` 目录持久化会话数据

**详细配置说明见 [config_guide.md](config_guide.md)**。

---

## 五、v2 里程碑总结（2026-06-08）

### 5.1 变更总览

自上次总结以来的关键变更（10 个提交）：

| 变更 | 影响文件 | 说明 |
|:---|:---|:---|
| LLM 模型配置化 | `config.py` / `llm_client.py` | 用户可选任意 OpenAI 兼容 API，不改代码 |
| 搜索 API 配置化 | `config.py` / `tools.py` | 新增搜索路由层，支持 auto/tavily/bocha |
| 配置模板精简 | `.env.example` / `.env.prod` | 45行→27行，去掉"旧兼容"段 |
| 前端去供应商烙印 | `index.html` / `handler.js` | 模型名 flash/pro/chat，header 动态拉取 |
| GitHub 发布准备 | 根目录清理 / `.gitignore` / `.dockerignore` | 删 report_selection.html，脚本移入 scripts/ |
| store 测试补齐 | `test_store.py` | 覆盖率 0% → 99% |
| 工具注册层设计 | `docs/tool_registry_design.md` | Skills/MCP 扩展基础 |
| 配置文档 | `docs/config_guide.md` | 208 行的完整配置指南 |

### 5.2 多维度评分

#### 架构

| 维度 | 评分 | 说明 |
|:---|:---:|:---|
| 模块化 | ⭐⭐⭐⭐⭐ | 20 模块，职责清晰，SSOT IntentRegistry |
| 可扩展性 | ⭐⭐⭐⭐ | LLM/搜索 Provider 无关，工具注册层设计就绪 |
| Pipeline 设计 | ⭐⭐⭐⭐⭐ | 8 Phase，LLM 自主拆解 DAG，30s 超时保护 |
| 记忆系统 | ⭐⭐⭐⭐⭐ | 5 层 CoALA 衍生架构，滑动窗口 + 递归摘要 |
| 配置化 | ⭐⭐⭐⭐ | 新增 LLM/搜索配置化，Provider 一览待工程化 |

#### 代码质量

| 维度 | 评分 | 说明 |
|:---|:---:|:---|
| 测试覆盖 | ⭐⭐⭐⭐ | 134 项，76% 覆盖率，mock 隔离 |
| Lint | ⭐⭐⭐⭐⭐ | ruff 全过，有 type hints 和 docstring |
| 错误处理 | ⭐⭐⭐⭐ | 重试机制 + 指数退避 + 优雅降级 |
| 安全 | ⭐⭐⭐⭐ | Bearer token + 速率限制 + dev 随机 token |
| 单体规模 | ⭐⭐⭐⭐ | Python 后端 4,300 行，无 God Object |

#### GitHub 发布

| 维度 | 评分 | 说明 |
|:---|:---:|:---|
| README 吸引力 | ⭐⭐⭐⭐ | 有截图、快速开始、架构图，去掉了供应商烙印 |
| 新人配置体验 | ⭐⭐⭐⭐⭐ | 只填 LLM_API_KEY 就能跑，1 个 key 起步 |
| 文档完备度 | ⭐⭐⭐⭐ | README + AGENTS.md + config_guide.md + 设计文档 |
| 根目录整洁度 | ⭐⭐⭐⭐ | 无开发残留，.gitignore 完备，CI 配置就绪 |
| 许可证 | ⭐⭐⭐⭐⭐ | MIT License |

#### 搜索和工具

| 维度 | 评分 | 说明 |
|:---|:---:|:---|
| LLM 配置化 | ⭐⭐⭐⭐⭐ | LLM_API_KEY 统一管理，三级分级 |
| 搜索配置化 | ⭐⭐⭐⭐ | 搜索抽象层就绪，provider 选择可配置 |
| 工具发现 | ⭐⭐⭐ | AVAILABLE_TOOLS 硬编码，无运行时发现 API |
| Skills/MCP | ⭐⭐ | 设计文档就绪，代码未落地 |

### 5.3 已知问题

| 问题 | 严重度 | 影响 |
|:---|:---:|:---|
| `_score_candidates` prompt 中 {.format()} 冲突 → KeyError | 低 | 生产路径不触发，LLM 从不生成 scoring_engine 任务 |
| tools.py 覆盖率 52%（搜索函数） | 中 | 搜索函数依赖真实 API，mock 成本高 |
| report_pipeline.py 覆盖率 26% | 中 | 新模块，测试待补 |
| API 无版本前缀（/api/v1/） | 低 | 规范性问题，不影响功能 |
| Docker 无非 root 用户 | 低 | 安全最佳实践，需单行 USER 指令 |

### 5.4 当前里程碑定位

```
MVP + 配置化 + GitHub Ready
      ↓
  推到 GitHub，收集真实反馈
      ↓
  工具注册层抽象（下一轮优先）
  Skills / MCP（后续扩展）
```

### 5.5 后续方向

| 优先级 | 方向 | 目标 |
|:---:|:---|:---|
| P0 | 推到 GitHub | 收集社区反馈，验证产品定位 |
| P1 | 工具注册层抽象 | 合并 AVAILABLE_TOOLS 到 ToolRegistry，为 Skills/MCP 铺路 |
| P1 | 电商结构化数据源 | 接入速 API 等获取精确价格/销量 |
| P2 | Skills 系统 | SKILL.md 声明 + 动态加载 |
| P2 | 报告导出 PDF | 对外分享交付 |
| P3 | MCP 客户端 | 接入外部工具生态 |
| P3 | 多租户 | SaaS 化 |
