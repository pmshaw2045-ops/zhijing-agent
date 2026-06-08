# 织镜 ZHÌJÌNG — 产品与技术总结

> 生成日期：2026-06-08
> 产品阶段：功能原型验证完成，单租户生产可部署
> 代码规模：后端 23 模块 ~3,900 行 + 前端 1,204 行

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
- **反思修正闭环**：报告生成后自动评分，低于 7 分触发重试修正（最多 2 次），保留最高分版本
- **可视化报告**：JSON 结构化数据 → 前端渲染引擎 → 包含指标卡片、柱状图、SWOT 矩阵、品牌对比卡、洞察框等 9 种组件（rc-* 体系）
- **工作记忆系统**：五层记忆架构（工作/短期/长期/主题/分析），滑动窗口 + 递归摘要
- **双源搜索**：博查（中文电商）+ Tavily（英文兜底），并行执行

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
|---|---|---|
| 后端框架 | Python 3.11 + FastAPI | 异步 SSE 流式响应 |
| LLM 主模型 | DeepSeek v4-pro / chat | pro 用于 DAG 拆解和反思，chat 用于其余 |
| 文生图 | 豆包 Seedream 5.0 | ARK API，真实摄影风格 |
| 搜索 | 博查 BochaAI + Tavily | 中文电商 / 英文兜底 |
| 前端 | 单文件 HTML/CSS/JS | 暖色调设计系统，CSS 变量体系 |
| 存储 | JSON 文件 | data/memory_store.json，async flush |
| 部署 | Docker + uvicorn | 单容器，健康检查 |

### 2.2 模块架构

```
backend/ (23 modules, ~3,900 lines)
├── agent_engine.py (604)   核心编排引擎，8 阶段 Pipeline
├── tools.py (395)          工具定义 + LLM 驱动的搜索/分析/提取
├── memory.py (433)         工作记忆，滑动窗口 + 递归摘要
├── report.py (253)         JSON 报告生成器，6 策略 + 渲染 Schema
├── intent_registry.py (227) 意图元数据中心（Single Source of Truth）
├── server.py (163)         FastAPI 应用入口，SSE 端点，API 路由
├── config.py (132)         三级 fallback 配置
├── intent.py (120)         IntentRouter + goal_to_text 共享函数
├── llm_client.py (121)     DeepSeek / 豆包 API 封装 + Token 追踪
├── observability.py (116)  指标收集器（请求量/延迟/Token）
├── conversation.py (128)   多轮对话场景检测 + 查询增强
├── decompose_engine.py (109) DAG 任务拆解（json_mode + 模板 fallback）
├── auth.py (100)           Bearer Token 认证 + 速率限制
├── precheck.py (140)       前置校验 + 澄清交互
├── reflect.py (60)         质量反思引擎
├── image_optimizer.py (53) 文生图 prompt 优化
└── harness/                管道基础设施层
    ├── tracer.py (98)      全链路追踪
    ├── router.py (87)      CostRouter: 复杂度判定 + 执行深度控制
    ├── executor.py (85)    ParallelExecutor: DAG 并行执行 + 超时保护
    ├── registry.py (83)    ToolRegistry: 工具注册中心
    └── dag_loader.py (66)  DAG 模板加载器（LLM 失败时的 fallback）

frontend/
└── index.html (1204)      SPA 前端
    ├── 渲染引擎：renderReport(json) → 9 种组件模板函数
    ├── 报告组件：rc-metrics / rc-bar-chart / rc-table / rc-swot / rc-compare
    ├── Console 面板：4 Tab（ALL/PIPELINE/STATE/MEMORY）+ 记忆面板
    └── 质量审查：绿色通过 / 橙色警告，评分 + 维度 + 修正历史

tests/ (93 passed, 2 xfailed)
├── conftest.py             mock OpenAI fixture
├── test_agent_engine.py    Pipeline 流程测试
├── test_config.py          配置测试
├── test_intent_registry.py 意图注册表测试
├── test_memory.py          记忆系统测试
├── test_pipeline.py        工具/拆解/预检流程测试
├── test_report_clean.py    报告清理测试
├── test_server.py          API 端点 + SSE 集成测试
└── test_tools.py           LLM 驱动工具测试
```

### 2.3 Agent Pipeline 架构

```
Phase 0: 多轮对话检测 → Scenario 识别 + 查询增强
Phase 1: LLM 意图识别 → 7 种意图判定 + IntentRegistry 路由 (deepseek-chat)
Phase 2: 前置校验     → 信息完整性检查 + 实体提取 + 澄清交互
Phase 3: LLM DAG 拆解 → 自主设计执行计划（json_mode, deepseek-v4-pro）
Phase 4+5: 工具映射   → ToolRegistry + ParallelExecutor 并行执行（30s 超时）
Phase 6: JSON 报告生成 → 6 策略路由 → LLM 输出 JSON → 前端渲染 (deepseek-chat)
Phase 7: 反思修正     → 质量评分 < 7 自动重试，最多 2 次 (deepseek-chat)
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

### 2.7 关键决策记录

| 决策 | 原因 |
|---|---|
| DeepSeek 直连（非 OpenRouter） | 降低延迟，中文优化好 |
| deepseek-chat 主力 + v4-pro 仅 DAG 拆解 | Token 成本优化 |
| 博查 + Tavily 双源并行 | 博查覆盖中文电商，Tavily 覆盖国际数据 |
| 反思闭环（7 分阈值，2 次重试） | 保证报告质量，控制 token 消耗 |
| 文生图默认真实摄影 | 避免卡通/插画式输出，符合电商场景 |
| JSON 文件持久化（非 SQLite） | 当前规模不需要关系型数据库 |
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

| 阶段 | 模型 | 理由 |
|---|---|---|
| Phase 1 意图识别 | `deepseek-chat` (V3) | 分类任务，低延迟 |
| Phase 3 DAG 拆解 | `deepseek-v4-pro` | 深度推理，max_tokens=2000 |
| Phase 6 报告生成 | `deepseek-chat` (V3) | JSON 输出，速度优先 |
| Phase 7 反思修正 | `deepseek-chat` (V3) | 快速质检 |
| 工具层 LLM 提取 | `deepseek-chat` (V3) | 结构化提取 |
| 记忆压缩摘要 | `deepseek-chat` (V3) | max_tokens=200 |

---

## 四、生产部署

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
