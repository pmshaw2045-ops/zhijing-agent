# 织镜 ZHÌJÌNG — 产品与技术总结

> 生成日期：2026-06-10（v2.1 RAG & SQLite）
> 产品阶段：GitHub 发布就绪，单租户生产可部署
> 代码规模：后端 22 模块 ~4,700 行 + 前端 ~1,170 行 + 测试 12 文件 ~3,000 行
> CI: GitHub Actions（pytest + npm test + Docker），全绿

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
- **工作记忆系统**：六层记忆架构（工作/短期/长期/主题/分析/RAG语义），滑动窗口 + 递归摘要 + 同义词桥接
- **语义检索（RAG）**：LLM embedding → SQLite 向量存储 → 余弦相似度排序，三层兜底（语义→同义词→关键词）
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

| 层 | 技术选型 | 说明 |
|:---|:---|:---|
| 后端框架 | Python 3.11 + FastAPI | 异步 SSE 流式响应 |
| LLM | 任意 OpenAI 兼容 API（可配置） | 三级模型分级 flash/pro/chat |
| 文生图 | 豆包 Seedream 5.0（可替换） | ARK API，真实摄影风格 |
| 搜索 | 配置化路由：Tavily / 博查 | 统一 SEARCH_API_KEY，支持 auto/tavily/bocha |
| 前端 | 单文件 HTML/CSS/JS | 暖色调设计系统，CSS 变量体系 |
| 存储 | SQLite 默认（WAL模式 并发安全） | 含向量表，首次运行自动从 JSON 迁移 |
| 部署 | Docker + uvicorn | 单容器，健康检查，Bearer Token 认证 |

### 2.2 模块架构

```
backend/ (22 modules, ~4,700 lines)
├── agent_engine.py (506)    核心编排引擎，8 阶段 Pipeline
├── tools.py (444)           工具定义 + 搜索路由层 + LLM 驱动分析
├── memory.py (590)          六层记忆 + RAG 语义检索（embedding + 同义词 + 向量）
├── report.py (255)          JSON 报告生成器，6 策略 + 渲染 Schema
├── intent_registry.py (243) 意图元数据中心（Single Source of Truth）
├── server.py (222)          FastAPI 应用入口，SSE 端点，API 路由
├── config.py (170)          配置化 Provider（LLM/搜索/存储）+ 三级 fallback
├── intent.py (133)          IntentRouter + goal_to_text 共享函数
├── llm_client.py (194)      LLM API 封装 + 重试机制 + Token 追踪
├── observability.py (116)   指标收集器（请求量/延迟/Token）
├── conversation.py (247)    多轮对话场景检测 + 查询增强
├── decompose_engine.py (103) DAG 任务拆解（json_mode + 模板 fallback）
├── auth.py (114)            Bearer Token 认证 + 速率限制
├── precheck.py (137)        前置校验 + 澄清交互
├── reflect.py (57)          质量反思引擎
├── store.py (186)           SQLite 存储后端（sessions + long_term + memory_vectors 三表）
├── report_pipeline.py (64)  报告管道辅助函数
├── logging_setup.py (73)    日志配置
├── startup_diag.py (232)    启动自检
└── harness/ (416)           管道基础设施层
    ├── tracer.py (98)       全链路追踪
    ├── router.py (77)       CostRouter: 复杂度判定 + 执行深度控制
    ├── executor.py (95)     ParallelExecutor: DAG 并行执行 + 超时保护
    ├── registry.py (83)     ToolRegistry: 工具注册中心
    └── dag_loader.py (63)   DAG 模板加载器（LLM 失败时的 fallback）

frontend/ (~1,170 lines)
├── index.html (109)         SPA 骨架
├── style.css (264)          CSS 设计系统
├── render.js (68)           报告渲染引擎（9 种组件）
├── handler.js (566)         SSE 事件处理 + Console 面板（含 memory_search）
├── sse.js (150)             SSE 流式 + 自动重连 + sendMessage
├── console.js (25)          Console 日志
└── tests/ (5 files, 57 passed)

tests/ (12 files, 176 passed)
├── test_agent_engine.py (458)     Pipeline 流程测试
├── test_config.py (60)            配置测试
├── test_conversation.py (181)     多轮对话
├── test_intent_registry.py (73)   意图注册表
├── test_llm_client.py (185)       重试机制
├── test_logging_setup.py (109)    日志
├── test_memory.py (111)           记忆系统 + 余弦相似度
├── test_memory_history.py (100)   语义检索 + 同义词匹配
├── test_pipeline.py (136)         工具/拆解/预检流程
├── test_report_clean.py (57)      报告清理
├── test_server.py (314)           API 端点 + SSE 集成
├── test_store.py (202)            SQLite 存储后端
└── test_tools.py (270)            LLM 驱动工具
```

覆盖率的坑：
- tools.py 52%（搜索函数依赖网络，mock 覆盖不全）
- memory.py 57%（embedding/检索代码调用LLM，test mock后覆盖率分布不均）
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
            → quality_review → memory_search → result → summary → done
```

### 2.4 记忆系统架构

基于 CoALA 论文的简化落地版 + RAG 语义检索：

| 层 | 内容 | 存储 | 注入 |
|---|---|---|---|
| L1 工作记忆 | 当前任务上下文 + intent + entities | SQLite working | MD 摘要 |
| L2 短期记忆 | 滑动窗口内原始对话 + 递归摘要 | SQLite conversation + summary | MD 最近对话 |
| L3 主题上下文 | 品类/品牌/季节/平台偏好 | SQLite topic_context | MD 主题偏好 |
| L4 分析历史 | record_analysis → title 提取 | SQLite analysis_history | MD 最近分析 |
| L5 长期记忆 | domains/brands/seasons/user_prefs | SQLite long_term | 按需注入 |
| L6 RAG 语义 | LLM embedding + 余弦相似度排序 | SQLite memory_vectors 表 | 近似度排名 top-5 |

- 压缩策略：滑动窗口溢出时 LLM 递归摘要（异步，不阻塞主流程）
- 并发保护：threading.Lock + mark_dirty/async flush（SQLite WAL模式）
- 注入格式：get_injectable_context() → Markdown
- 检索兜底：语义检索 → 同义词映射（8类目体系） → 关键词匹配

### 2.5 前端渲染架构

```
SSE 事件流
  ├─ result          → JSON.parse → renderReport(json)
  │                     └─ 9 种组件模板函数
  ├─ quality_review  → 质量审查区块（评分 + 维度 + 修正历史）
  ├─ memory_search   → 语义检索过程展示（方法/评分/来源/延迟）
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
| SQLite 默认存储（含向量表） | 零依赖向量检索，SQLite WAL 模式并发安全 |
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
| Phase 5 代码整顿 | 死代码清理/test覆盖/CI双线/前端57测试 | ✅ 完成 |
| Phase 6 RAG记忆 | SQLite默认 + 语义检索 + 同义词映射 + Console透明化 | ✅ 完成 |

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

## 五、v2 里程碑总结（2026-06-10）

### 5.1 变更总览

自上次总结以来的关键变更（30+ 个提交，代码整顿 + RAG 记忆系统）：

| 变更 | 影响文件 | 说明 |
|:---|:---|:---|
| 代码整顿 P0-P2 | agent_engine / tools / etc | 删除 148 行死代码，修复 format 冲突，事件循环解阻塞 |
| 前端测试体系 | frontend/tests/ | 14 → 57 测试（render/handler/sse/console 全覆盖） |
| RAG 语义检索 | memory / store / llm_client | LLM embedding + SQLite向量表 + 余弦相似度 |
| SQLite 默认存储 | memory / store / config | 自动迁移JSON，memory_vectors 三表 |
| 同义词映射 | memory.py | 8类目体系桥接语义鸿沟 |
| CI 完善 | .github/workflows/ | pytest + npm test + Docker 三job，修复 pytest-cov 版本 |
| Agent评测体系 | scripts/ + frontend/eval.html | 42条私有Benchmark，规则判分+LLM-as-Judge，可视化页面，CI/CD评测工作流 |
| 文档同步 | AGENTS / README / timeline / product_summary | 全量更新 |

### 5.2 多维度评分

#### 架构

| 维度 | 评分 | 说明 |
|:---|:---:|:---|
| 模块化 | ⭐⭐⭐⭐⭐ | 22 模块，职责清晰，SSOT IntentRegistry |
| 可扩展性 | ⭐⭐⭐⭐⭐ | LLM/搜索/存储 Provider 无关 |
| Pipeline 设计 | ⭐⭐⭐⭐⭐ | 8 Phase，LLM 自主拆解 DAG，30s 超时保护 |
| 记忆系统 | ⭐⭐⭐⭐⭐ | 6 层 + RAG 语义检索 + SQLite 向量表 |
| 存储 | ⭐⭐⭐⭐ | SQLite 默认，零依赖向量检索 |

#### 代码质量

| 维度 | 评分 | 说明 |
|:---|:---:|:---|
| 测试覆盖 | ⭐⭐⭐⭐ | 176 项，76% 覆盖率，CI 三线 |
| Lint | ⭐⭐⭐⭐⭐ | ruff 全过+ CI 门禁 |
| 错误处理 | ⭐⭐⭐⭐ | 重试机制 + 指数退避 + 三层兜底 |
| 安全 | ⭐⭐⭐⭐ | Bearer token + 速率限制 + CI secret 扫描 |
| 单体规模 | ⭐⭐⭐⭐ | Python 后端 4,700 行，零 dir() 反射 |

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
| LLM embedding 一致性低（相同文本~0.57） | 中 | 语义检索排名不理想，依赖同义词+关键词兜底 |
| tools.py 覆盖率 52%（搜索函数） | 中 | 搜索函数依赖真实 API，mock 成本高 |
| memory.py 覆盖率 57%（RAG代码） | 中 | embedding/检索调LLM，mock后覆盖不均 |
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
