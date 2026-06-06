# AGENTS.md — 织镜 ZHÌJÌNG 服饰电商AI Agent

> 项目类型：AI Agent 产品 (Web Application)
> 目标用户：服饰类电商商家（选品/运营/商品企划）
> 技术栈：Python FastAPI + DeepSeek API + HTML/JS
> 版本：v1.1.0

---

## v1.1.0 变更 (2026-06-05)

| 变更 | 内容 |
|------|------|
| P3 模型分级 | Phase 1 意图识别 → flash; Phase 3 DAG拆解 → pro; Phase 6 报告 → pro; Phase 7 反思 → pro |
| P0 LLM驱动工具 | trend_analyze/price_analyze/competitive_analyze/scoring_engine 全部改为LLM提取 |
| P2 DAG差异化 | 6种意图各自独立DAG模板 (选品/竞品/趋势/文案/定价/排期) |
| P1 反思修正环 | 新增Phase 7: LLM质检 (数据一致性+Goal对齐+可落地性三维评分) |
| P4 记忆注入 | 意图识别注入对话历史; 报告生成注入用户偏好和历史品类 |

## 角色分工

| 角色 | 职责 | 交付物 |
|------|------|--------|
| **PM (产品经理)** | 需求分析、PRD、功能规格、验收标准 | `PRD.md` |
| **Backend Dev** | Agent引擎、LLM调用编排、记忆系统、API | `backend/` |
| **Frontend Dev** | 交互UI、Console可视化、API对接 | `frontend/` |
| **QA** | 端到端测试、边界case验证 | 测试报告 |

## 核心架构 v7

```
用户浏览器 (frontend/index.html)
    │  POST /api/chat  (SSE streaming)
    ▼
FastAPI Server (backend/server.py)
    │
    ├── Agent Engine (backend/agent_engine.py)
    │   ├── Phase 1: 意图识别      → deepseek-v4-flash (轻量+记忆注入)
    │   ├── Phase 2: 前置校验      → 规则引擎 (阻塞/hint分离)
    │   ├── Phase 3: DAG任务拆解   → deepseek-v4-pro (按意图差异化)
    │   ├── Phase 4: 工具映射      → 规则引擎
    │   ├── Phase 5: 执行调度      → 执行引擎 + LLM驱动工具
    │   ├── Phase 6: 报告生成      → deepseek-v4-pro (记忆注入)
    │   └── Phase 7: 反思修正      → deepseek-v4-pro (三维评分)
    │
    ├── Memory System (backend/memory.py)
    │   ├── 短期记忆: 会话上下文窗口 → 注入意图识别prompt
    │   ├── 工作记忆: 当前任务状态 → 注入报告生成prompt
    │   └── 长期记忆: JSON文件持久化
    │
    └── Tools (backend/tools.py) — 全LLM驱动
        ├── web_search: Tavily API 真实搜索
        ├── trend_analyze: LLM提取趋势洞察
        ├── price_analyze: LLM提取价格带
        ├── competitive_analyze: LLM分析竞品格局
        ├── scoring_engine: LLM多维度评分
        └── report_generate: 标记 → 由agent_engine接管
```

## 模型使用策略 (v1.1.1 混合策略)

| 阶段 | 模型 | 理由 |
|------|------|------|
| Phase 1 意图识别 | `deepseek-chat` (V3) | 分类任务，低延迟优先 |
| Phase 3 DAG拆解 | `deepseek-v4-pro` | 唯一需要深度推理的环节 |
| Phase 6 报告生成 | `deepseek-chat` (V3) | 长文生成，速度优先 |
| Phase 7 反思修正 | `deepseek-chat` (V3) | 快速质检 |
| 工具层LLM提取 | `deepseek-chat` (V3) | 结构化提取，低温 |

## 工具数据源 (全LLM驱动)

| Tool | 数据源 | 驱动方式 |
|------|--------|----------|
| web_search | Tavily API | 真实搜索 |
| trend_analyze | LLM从搜索结果提取 | LLM推理 |
| price_analyze | LLM从搜索结果提取 | LLM推理 |
| competitive_analyze | LLM从搜索结果提取 | LLM推理 |
| scoring_engine | LLM综合评分 | LLM推理 |

## DAG差异化 (6种意图)

| 意图 | DAG结构 | 任务数 |
|------|---------|--------|
| selection 选品 | T1→(T2∥T3∥T4)→T5→T6 | 6 |
| competitive 竞品 | (T1∥T2)→(T3∥T4)→T5 | 5 |
| trend 趋势 | T1→T2→T3→T4 | 4 |
| copy 文案 | T1→T2→T3 | 3 |
| pricing 定价 | T1→(T2∥T3)→T4 | 4 |
| launch 排期 | (T1∥T2)→T3→T4 | 4 |

## Phase 7 反思修正

三维评分 (0-10):
- **数据一致性**: 报告结论是否与可用数据一致
- **目标对齐**: 是否回答了用户核心问题
- **可落地性**: 结论是否有具体可执行建议

overall < 6 → 报告末尾追加质量风险标注
有 warnings → 追加提示标注

## 文件结构

```
/Users/admin/Desktop/test/fashion-agent-v2/
├── AGENTS.md          ← 本文件
├── PRD.md             ← 产品需求文档
├── backend/
│   ├── server.py      ← FastAPI 主服务
│   ├── agent_engine.py← Agent Pipeline v7
│   ├── memory.py      ← 记忆系统
│   ├── tools.py       ← 工具实现 v3 (全LLM驱动)
│   ├── llm_client.py  ← DeepSeek API v6 (同步+异步)
│   └── requirements.txt
├── frontend/
│   └── index.html     ← SPA 前端
├── data/
│   └── memory_store.json ← 持久化记忆
└── start.sh           ← 一键启动脚本
```

## API 设计

### POST /api/chat
```json
// Request
{
  "message": "帮我分析2026夏季法式茶歇裙的选品机会",
  "session_id": "sess_xxx",
  "mode": "selection"  // selection|competitive|trend|copy|pricing|launch
}

// Response (SSE Stream)
data: {"type":"phase","phase":"intent","data":{...}}
data: {"type":"phase","phase":"precheck","data":{...}}
data: {"type":"phase","phase":"decompose","data":{...}}
data: {"type":"phase","phase":"tool_mapping","data":{...}}
data: {"type":"phase","phase":"execute","data":{...}}
data: {"type":"phase","phase":"report","data":{...}}
data: {"type":"phase","phase":"reflect","data":{"scores":{...},"passed":true}}
data: {"type":"result","content":"...html..."}
data: {"type":"done"}
```

## 验收标准

1. ✅ Agent能正确识别6种意图模式
2. ✅ 真实调用DeepSeek LLM进行意图识别和任务拆解
3. ✅ DAG任务流按意图差异化，非统一模板
4. ✅ 趋势/价格/竞品工具由LLM驱动提取，非关键词匹配
5. ✅ 模型分级: flash做轻量, pro做重量
6. ✅ Phase 7反思修正环，三维评分
7. ✅ 记忆注入: 对话历史→意图识别, 偏好→报告生成
8. ✅ Console面板实时展示Pipeline执行过程
9. ✅ 前端与后端通过SSE实时通信
10. ✅ 报告内容由LLM真实生成，非硬编码
