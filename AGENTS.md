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
    │   ├── Agent Engine (backend/agent_engine.py) — 490行
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
    │   ├── L5 长期记忆: domains/brands/seasons/user_prefs
    │   └── RAG语义检索: LLM embedding → SQLite向量 → 余弦相似度排名
    │
    ├── Storage (backend/store.py)
    │   ├── SQLiteBackend: 默认存储（WAL模式并发安全）
    │   ├── sessions/long_term/memory_vectors 三表
    │   └── JSON文件兼容（STORE_BACKEND=json）
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
├── AGENTS.md              ← 本文件
├── docs/                  ← 12 文档
├── backend/               ← 22 模块 / 4,700+ 行
│   ├── agent_engine.py    506行  Agent Pipeline
│   ├── memory.py          590行  六层记忆系统 + RAG语义检索
│   ├── tools.py           444行  8个工具实现
│   ├── report.py          255行  JSON报告生成器
│   ├── intent_registry.py 243行  意图元数据中心
│   ├── config.py          170行  配置管理
│   ├── llm_client.py      194行  LLM客户端
│   ├── precheck.py        137行  前置校验引擎
│   ├── intent.py          133行  意图识别路由 + goal_to_text
│   ├── observability.py   116行  指标收集
│   ├── conversation.py    247行  多轮场景检测
│   ├── decompose_engine.py 103行 DAG自主拆解
│   ├── store.py           186行  SQLite存储后端（向量表+CRUD）
│   ├── auth.py            114行  认证+限流
│   ├── reflect.py          57行  反思引擎
│   ├── report_pipeline.py  64行  报告管道辅助函数
│   ├── startup_diag.py    232行  启动自检
│   ├── logging_setup.py    73行  日志配置
│   └── harness/           416行  管道基础设施
│       ├── tracer.py       98行  全链路追踪
│       ├── router.py       77行  CostRouter
│       ├── executor.py     95行  ParallelExecutor
│       ├── registry.py     83行  ToolRegistry
│       └── dag_loader.py   63行  DAG模板加载
├── frontend/
│   ├── index.html         109行 HTML骨架+全局state
│   ├── style.css          264行 CSS设计系统
│   ├── render.js           68行 报告渲染引擎(R.* + renderReport)
│   ├── console.js          25行 Console日志(clog/clearConsole)
│   ├── sse.js             150行 SSE流式+重试+sendMessage
│   ├── handler.js         554行 SSE事件处理+layout修复
│   └── tests/             5个测试文件 / 57 passed
├── tests/                 12个测试文件 / 176 passed
│   ├── test_agent_engine.py  19 Pipeline流程
│   ├── test_config.py         5 配置加载
│   ├── test_conversation.py  26 多轮对话
│   ├── test_intent_registry.py 11 注册表
│   ├── test_llm_client.py    15 重试机制
│   ├── test_logging_setup.py  8 日志
│   ├── test_memory.py        14 记忆系统 + 余弦相似度
│   ├── test_memory_history.py 10 语义检索 + 同义词匹配
│   ├── test_pipeline.py       8 DAG/预检
│   ├── test_report_clean.py   8 报告清理
│   ├── test_server.py        13 API端点+SSE
│   ├── test_store.py         16 SQLite后端
│   └── test_tools.py         23 LLM驱动工具
├── .github/workflows/
│   └── test.yml           CI: pytest + npm test（双作业并行）
└── data/
    ├── memory_store.json  持久化记忆
    └── report_cache.json  24h报告缓存
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
data: {"type":"memory_search","data":{"query":"...","results":[...],"latency_ms":123,"method":"semantic|keyword","injected_count":1}}
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
7. ✅ 六层记忆 + RAG语义检索（LLM embedding → SQLite向量 → 余弦相似度）
8. ✅ 服饰类目同义词映射（8个类目体系，零依赖）
9. ✅ Console面板实时展示Pipeline+Prompt+语义检索过程
10. ✅ JSON Schema前端渲染，根除类名幻觉
11. ✅ 前置校验entity驱动+user_input兜底
12. ✅ 233项自动化测试（176后端 + 57前端） + GitHub Actions CI（pytest + npm test + Docker）
