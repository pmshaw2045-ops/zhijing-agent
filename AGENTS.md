# AGENTS.md — 织镜 ZHÌJÌNG 服饰电商AI Agent

> 项目类型：AI Agent 产品 (Web Application)
> 目标用户：服饰类电商商家（选品/运营/商品企划）
> 技术栈：Python 3.11 + FastAPI + DeepSeek + 豆包Seedream + HTML/JS/CSS
> 版本：v2.0.0

---

## v2.0.0 架构重构 (2026-06-06)

| 变更 | 内容 |
|------|------|
| LLM自由拆解DAG | 不再依赖固定模板，LLM根据意图+工具列表自主设计；模板仅作fallback |
| JSON报告渲染 | 后端输出结构化JSON → 前端9种模板函数渲染，根除LLM类名幻觉 |
| IntentRegistry | 7种意图集中注册（mode/name/display/complexity/decompose_rule/intent_signals/precheck/relevant_tools/dag） |
| 记忆系统v2 | 滑动窗口+递归摘要+MD格式注入+五层记忆架构 |
| 工具按意图过滤 | relevant_tools字段，非文生图意图看不到image_generate |
| 前置校验rewrite | entity驱动+user_input兜底+默认规则，不再依赖黑名单 |
| 质量控制 | 通过/不通过/警告三种状态独立SSE事件，反思评分阈值7分 |

## 核心架构 v8

```
用户浏览器 (frontend/index.html)
    │  POST /api/chat  (SSE streaming)
    ▼
FastAPI Server (backend/server.py)
    │
    │   ├── Agent Engine (backend/agent_engine.py) — 868行
    │   │   ├── [DEPRECATED v7] 旧意图/预检/报告/反思方法已标记，由提取模块替代
    │   ├── Phase 0: 多轮对话检测 → conversation.py
    │   ├── Phase 1: 意图识别       → deepseek-chat (记忆注入)
    │   ├── Phase 2: 前置校验       → PrecheckEngine (entity驱动)
    │   ├── Phase 3: DAG任务拆解    → deepseek-v4-pro (LLM自主, 模板fallback)
    │   ├── Phase 4: 工具映射       → ToolRegistry
    │   ├── Phase 5: 执行调度       → ParallelExecutor + LLM驱动工具
    │   ├── Phase 6: 报告生成       → ReportBuilder (JSON Schema)
    │   └── Phase 7: 反思修正       → ReflectionEngine (三维评分, 最多2次重试)
    │
    ├── IntentRegistry (backend/intent_registry.py) — Single Source of Truth
    │   └── 7种意图 × 9字段: mode/name/display/complexity/decompose_rule/
    │       intent_signals/precheck/relevant_tools/dag
    │
    ├── Memory System (backend/memory.py)
    │   ├── L1 工作记忆: 当前任务上下文
    │   ├── L2 短期记忆: 滑动窗口(10条)+递归摘要
    │   ├── L3 主题上下文: 品类/品牌/季节/平台偏好
    │   ├── L4 分析历史: record_analysis → title提取
    │   └── L5 长期记忆: domains/brands/seasons/user_prefs
    │
    ├── Precheck Engine (backend/precheck.py)
    │   ├── entity驱动: category > subject_in_input > goal.品类
    │   ├── user_input兜底: _PRODUCT_KW关键词匹配
    │   └── 默认规则: intent数据缺失时启用require_analysis_object
    │
    └── Tools (backend/tools.py) — 全LLM驱动
        ├── web_search: Tavily API
        ├── bocha_search: 博查BoChaAI (中文电商)
        ├── trend_analyze: LLM提取趋势洞察
        ├── price_analyze: LLM提取价格带
        ├── competitive_analyze: LLM分析竞品格局
        ├── scoring_engine: LLM多维度评分
        ├── report_generate: JSON Schema报告
        └── image_generate: 豆包Seedream 5.0
```

## 意图类型与工具绑定

| 意图 | 可用工具 | 前置校验 |
|------|------|------|
| 单品选品分析 | bocha,web,trend,price,competitive,scoring,report (7) | require_analysis_object |
| 多品牌竞品对标 | bocha,web,competitive,report (4) | require_analysis_object + require_brands |
| 品类趋势洞察 | bocha,web,trend,report (4) | require_analysis_object |
| 商品文案生成 | bocha,web,report (3) | require_analysis_object |
| 定价策略分析 | bocha,web,price,competitive,report (5) | require_analysis_object |
| 上新排期优化 | bocha,web,report (3) | require_analysis_object |
| 文生图 | image_generate (1) | image_quality |

## 模型使用策略

| 阶段 | 模型 | 理由 |
|------|------|------|
| Phase 1 意图识别 | `deepseek-chat` (V3) | 分类任务，低延迟 |
| Phase 3 DAG拆解 | `deepseek-v4-pro` | 深度推理，max_tokens=2000 |
| Phase 6 报告生成 | `deepseek-chat` (V3) | JSON输出，速度优先 |
| Phase 7 反思修正 | `deepseek-chat` (V3) | 快速质检 |
| 工具层LLM提取 | `deepseek-chat` (V3) | 结构化提取 |
| 记忆压缩摘要 | `deepseek-chat` (V3) | max_tokens=200 |

## Prompt 数据注入规范

所有 Phase 在将用户需求注入 prompt 时，统一使用自然语言渲染而非 raw JSON。

| ✅ 正确做法 | ❌ 反面做法 |
|---|---|
| `用户目标: {goal_to_text(goal)}` → `品类：连衣裙，时间范围：2026夏季` | `需求: {json.dumps(goal, ...)}` → `{"品类": "连衣裙", "时间范围": "2026夏季", "风格": null}` |

规则：
- 去 null / [] / "未指定" / "None" — 无信息字段不注入
- 去 JSON 结构符号（`{}` `""` `,` 缩进）— 纯自然语言
- list 字段用"、"连接而非 Python 列表表示
- 共享函数 `goal_to_text()` 在 `backend/intent.py` 中，所有 prompt builder 统一调用
- 当前通过区域：DecomposeEngine (decompose_engine.py) ✅ ReportBuilder (report.py) ✅ ReflectionEngine (reflect.py) ✅

## DAG 拆解策略

**LLM自主拆解** (当前):
- 仅提供意图类型+目标+relevant_tools+分解规则
- 无模板干扰，LLM自主设计任务流
- 兼容 `depends_on`/`deps`/`nodes`/`dag` 等多种LLM输出变体
- 失败时fallback到 registry 中的 dag 模板

**fallback模板** (兜底):
- 注册在 intent_registry 的 `dag` 字段
- LLM返回非JSON或缺少`tasks`字段时触发
- 文生图意图跳过LLM拆解，直接走固定模板

## Phase 7 反思修正

三维评分 (0-10):
- **数据一致性**: 报告结论是否与可用数据一致
- **目标对齐**: 是否回答了用户核心问题
- **可落地性**: 结论是否有具体可执行建议

流程: overall < 7 → 自动重试 (最多2次, 保留最高分) → 追加质量审查区块

## 文件结构

```
本项目根目录（`./`）
├── AGENTS.md              ← 本文件
├── docs/                  ← 文档目录
│   ├── product_summary.md     产品与技术总结
│   ├── product_roadmap.md     产品路线图
│   ├── architecture_optimization.md  架构优化方案
│   ├── sse_reconnect_design.md   SSE重连设计
│   ├── production_plan.md     生产级优化执行计划
│   ├── test_cases.md          测试用例
│   ├── deploy.md              部署指南
│   └── archive/               历史存档
├── backend/               ← 23 模块 / 4,147 行
│   ├── agent_engine.py    616行  Agent Pipeline
│   ├── memory.py          433行  五层记忆系统
│   ├── tools.py           397行  8个工具实现
│   ├── report.py          255行  JSON报告生成器
│   ├── intent_registry.py 227行  意图元数据中心
│   ├── config.py          132行  配置管理
│   ├── llm_client.py      138行  LLM客户端
│   ├── precheck.py        140行  前置校验引擎
│   ├── intent.py          120行  意图识别路由 + goal_to_text
│   ├── observability.py   116行  指标收集
│   ├── conversation.py    128行  多轮场景检测
│   ├── decompose_engine.py 109行 DAG自主拆解
│   ├── storage.py         147行  存储后端
│   ├── auth.py            100行  认证+限流
│   ├── reflect.py         62行   反思引擎
│   ├── image_optimizer.py 53行   文生图优化
│   ├── startup_diag.py    232行  启动自检
│   └── harness/           421行  管道基础设施
│       ├── tracer.py      98行   全链路追踪
│       ├── router.py      80行   CostRouter
│       ├── executor.py    95行   ParallelExecutor
│       ├── registry.py    83行   ToolRegistry
│       └── dag_loader.py  66行   DAG模板加载
├── frontend/
│   ├── index.html         398行 HTML骨架+全局state
│   ├── style.css          247行 CSS设计系统
│   ├── render.js           71行 报告渲染引擎(R.* + renderReport)
│   ├── console.js          26行 Console日志(clog/clearConsole)
│   ├── sse.js             145行 SSE流式+重试+sendMessage
│   ├── handler.js         315行 SSE事件处理+layout修复
│   └── tests/             2个测试 / 14 passed
├── tests/                 9个测试文件 / 93passed+2xfailed
│   ├── test_agent_engine.py  Pipeline流程
│   ├── test_config.py
│   ├── test_intent_registry.py
│   ├── test_memory.py
│   ├── test_pipeline.py   工具/拆解/预检
│   ├── test_report_clean.py
│   ├── test_server.py     API端点+SSE
│   └── test_tools.py      LLM驱动工具
├── .github/workflows/
│   └── test.yml           CI自动运行pytest+ruff
└── data/
    └── memory_store.json  持久化记忆
```

## API 设计

### POST /api/chat
```json
// Request
{
  "message": "帮我分析2026夏季法式茶歇裙的选品机会",
  "session_id": "sess_xxx",
  "mode": "selection"
}

// Response (SSE Stream)
data: {"type":"phase","phase":"intent","status":"done","data":{"intent":{...}}}
data: {"type":"phase","phase":"precheck","status":"done","data":{"checks":{...}}}
data: {"type":"clarify","message":"..."}  // 信息不足时
data: {"type":"phase","phase":"decompose","status":"done","data":{"tasks":[...],"_llm_generated":true}}
data: {"type":"phase","phase":"tool_mapping","status":"done","data":{"mappings":[...]}}
data: {"type":"phase","phase":"execute","status":"step","data":{...}}
data: {"type":"result","content":"{json报告}"}
data: {"type":"quality_review","data":{"passed":true,"scores":{...}}}
data: {"type":"summary","data":{"tokens":...,"latency_ms":...}}
data: {"type":"done"}
```

### GET /api/memory/{session_id}
返回完整记忆状态：stats + working_memory + topic_context + analysis_history + long_term + conversation

## 验收标准

1. ✅ 7种意图LLM识别+路由
2. ✅ DAG由LLM自主设计，模板仅fallback
3. ✅ 工具按意图过滤（relevant_tools）
4. ✅ LLM驱动趋势/价格/竞品/评分工具
5. ✅ 模型分级: flash轻量/pro深度
6. ✅ Phase 7反思修正，三维评分≥7阈值
7. ✅ 五层记忆架构，滑动窗口+递归摘要
8. ✅ Console面板实时展示Pipeline+Prompt
9. ✅ JSON Schema前端渲染，根除类名幻觉
10. ✅ 前置校验entity驱动+user_input兜底
11. ✅ 32项自动化测试 + GitHub Actions CI
