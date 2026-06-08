# 织镜 ZHÌJÌNG v2.0 — 架构升级方案

> 版本：v2.0-plan | 日期：2026-06-05 | 状态：设计中

---

## 一、当前架构诊断

### 1.1 结构性问题

```
当前架构:
┌──────────────┐
│  server.py   │  ← FastAPI SSE
├──────────────┤
│ agent_engine │  ← 800行单体，6种职责混杂
│   · flow     │     流程编排
│   · llm      │     LLM调用管理
│   · tools    │     工具路由
│   · memory   │     记忆管理
│   · report   │     报告生成
│   · reflect  │     质量审查
├──────────────┤
│  tools.py    │  ← 工具实现
│  memory.py   │  ← 写入黑洞（存了42个session从未检索）
│  llm_client  │  ← API封装
└──────────────┘

问题:
1. 无抽象层 → 加工具/改流程必碰 engine
2. 记忆系统形同虚设 → 写入无检索
3. Pipeline 静态执行 → 简单查询也要6次LLM调用
4. 单轮对话 → 无多轮上下文延续
5. DAG硬编码在 engine 里 → 无法热更新
```

### 1.2 目标架构

```
v2.0 架构:
┌────────────────────────────────────────────────────────┐
│                      server.py                          │
│                  (FastAPI SSE, 不感知业务)               │
├────────────────────────────────────────────────────────┤
│                   Orchestrator                          │
│   ┌──────────┐  ┌─────────┐  ┌──────────┐             │
│   │ CostRouter│  │ContextMgr│  │ DAGLoader│             │
│   │ 动态路由  │  │多轮上下文│  │ YAML配置 │             │
│   └──────────┘  └─────────┘  └──────────┘             │
├────────────────────────────────────────────────────────┤
│              Pipeline Harness (执行抽象层)              │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│   │ToolRegist│  │ParallelExe│  │TraceColl │            │
│   │ 工具注册  │  │ 并行执行  │  │全链路追踪│            │
│   └──────────┘  └──────────┘  └──────────┘            │
├────────────────────────────────────────────────────────┤
│                     Domain Layer                        │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│   │  tools   │  │  memory  │  │ llm_client│            │
│   │ (不变)   │  │ (增强)   │  │ (不变)    │            │
│   └──────────┘  └──────────┘  └──────────┘            │
├────────────────────────────────────────────────────────┤
│                     config/dags.yaml                    │
│                     (DAG配置外部化)                      │
└────────────────────────────────────────────────────────┘
```

---

## 二、四个优化模块详细设计

### 2.1 Pipeline Harness 抽象层

**目标**：将 agent_engine 的编排逻辑抽取为可复用的执行抽象

```
harness/
├── __init__.py           # 统一导出
├── registry.py           # ToolRegistry: 工具注册/发现/参数校验
├── executor.py           # ParallelExecutor: async.gather 真正并行
├── router.py             # CostRouter: 复杂度判定 + 执行深度控制
├── tracer.py             # TraceCollector: 全链路 trace 记录
└── dag_loader.py         # DAGLoader: 从 YAML 加载 DAG 配置
```

**ToolRegistry 接口**：
```python
class ToolRegistry:
    def register(name, func, schema)      # 注册工具
    def get(name) → Callable              # 获取工具函数
    def list_all() → List[ToolSchema]     # 列出所有工具
    def validate(tool_name, params) → bool # 参数校验
```

**ParallelExecutor 接口**：
```python
class ParallelExecutor:
    async def execute_dag(dag, registry, context) → List[TaskResult]
    # 真正并行：同 parallel_group 的任务用 asyncio.gather 并发
    # 依赖管理：自动按拓扑序调度
```

**CostRouter 接口**（详见 2.2）：
```python
class CostRouter:
    def classify(query, intent) → Complexity    # SIMPLE/MEDIUM/COMPLEX
    def select_dag(complexity, intent) → DAG     # 选择执行深度
    def estimate_tokens(dag) → int               # 估算 token 消耗
```

**TraceCollector 接口**：
```python
class TraceCollector:
    def start_trace(session_id, query) → trace_id
    def record_step(trace_id, phase, data, latency)
    def finish_trace(trace_id) → TraceReport
```

**DAGLoader 接口**：
```python
class DAGLoader:
    def load(mode) → DAG                        # 从 YAML 加载
    def reload() → None                         # 热更新（开发模式）
```

**改动影响范围**：
- agent_engine.py：从 800 行 → ~200 行（纯编排，调用 harness）
- 新增 harness/ 目录（~400 行）
- tools.py：不变（工具实现保持原样）
- llm_client.py：不变

### 2.2 CostRouter 动态路由

**目标**：根据查询复杂度决定执行深度，避免简单查询浪费 LLM 调用

**复杂度判定规则**：

| 维度 | SIMPLE (1) | MEDIUM (2) | COMPLEX (3) |
|------|-----------|------------|-------------|
| 意图类型 | copy | trend, pricing | selection, competitive, launch |
| 查询长度 | < 30 字 | 30-80 字 | > 80 字 |
| 品牌数量 | 0 | 1 | ≥ 2 |
| 是否追问 | follow-up | - | - |

**路由决策表**：

| 复杂度 | 执行策略 | 跳过环节 | 预期 LLM 调用 | Token 估算 |
|--------|---------|---------|-------------|-----------|
| SIMPLE | 轻量 DAG | trend_analyze, price_analyze, 反思 | 1-2 | ~2000 |
| MEDIUM | 标准 DAG | 反思（单轮通过） | 3-4 | ~5000 |
| COMPLEX | 完整 DAG + 反思 | 无 | 6-8 | ~12000 |

**判决逻辑**：
```python
def classify(query, intent) -> Complexity:
    score = 0
    if intent in ("selection", "competitive", "launch"):
        score += 2
    elif intent == "copy":
        score += 0
    else:
        score += 1
    
    if len(query) > 80: score += 1
    if len(query) < 30: score -= 1
    
    # 检测追问
    if is_followup(query): score -= 1
    
    if score <= 1: return SIMPLE
    if score == 2: return MEDIUM
    return COMPLEX
```

### 2.3 工作记忆增强

**目标**：从"只存 last_intent"升级为结构化上下文管理

**当前状态**：
```python
# memory.py 只存了:
working["last_intent"] = "单品选品分析"
conversation = [{"role": "user", "content": "..."}, ...]
knowledge_snippets = [{"content": "查询:...", "tags": [...]}]
```

**增强后**：
```python
class WorkingMemory:
    # 结构化上下文（跨 session 持久化）
    context = {
        "current_topic": {           # 当前分析主题
            "category": "连衣裙",
            "style": "法式",
            "sub_category": "茶歇裙",
            "price_range": "200-400",
            "fabric": "苎麻",
            "platforms": ["淘宝", "天猫"]
        },
        "user_preferences": {        # 用户偏好（跨 session 累积）
            "price_focus": "中端",
            "style_preferences": ["法式", "通勤"],
            "fabric_interests": ["苎麻", "天丝", "醋酸"],
            "target_market": "天猫"
        },
        "analysis_history": [        # 最近 5 次分析摘要
            {
                "query": "...",
                "intent": "单品选品分析",
                "category": "茶歇裙",
                "key_findings": "主力价格带200-400，苎麻面料趋势上升",
                "timestamp": "..."
            }
        ],
        "session_chain": []          # 当前会话的多轮对话链
    }
```

**注入策略**：
```python
def build_context(session_id, intent):
    memory = load_working_memory(session_id)
    
    parts = []
    
    # 1. 当前主题（如果与上次相同品类，注入上次关键结论）
    if memory.context["current_topic"]["category"]:
        parts.append(f"当前分析品类: {memory.context['current_topic']}")
        last = memory.context["analysis_history"][-1] if memory.context["analysis_history"] else None
        if last and last["category"] == memory.context["current_topic"]["category"]:
            parts.append(f"上轮关键发现: {last['key_findings']}")
    
    # 2. 用户偏好
    if memory.context["user_preferences"]["price_focus"]:
        parts.append(f"用户偏好价格带: {memory.context['user_preferences']['price_focus']}")
    
    # 3. 多轮对话链（最近3轮）
    chain = memory.context["session_chain"][-3:]
    if chain:
        parts.append("本轮对话上下文:")
        for turn in chain:
            parts.append(f"  用户: {turn['user']}")
            parts.append(f"  助手: {turn['assistant_summary']}")
    
    return "\n".join(parts)
```

**改动范围**：
- memory.py：新增 `WorkingMemory` 类，扩展现有 `MemorySystem`
- agent_engine.py：`_build_memory_context` 和 `_build_report_memory_context` 改为调用 WorkingMemory
- 每次分析完成后自动提取关键信息存入 working memory

### 2.4 多轮对话能力

**目标**：支持追问、深入分析、对比引用

**场景定义**：

| 场景 | 示例 | 处理策略 |
|------|------|---------|
| 深入追问 | "深入分析价格" | 聚焦上次报告的某个维度 |
| 对比引用 | "和上次茶歇裙的对比一下" | 加载上次分析结论，追加对比 |
| 条件变更 | "把价格改成300-500再分析" | 继承上下文，只修改指定参数 |
| 新主题 | "换个品类，分析通勤西装裤" | 更新主题，保留偏好 |

**实现方案**：

```python
class ConversationManager:
    def detect_scenario(query, last_intent, working_memory) -> Scenario:
        """检测当前查询的场景类型"""
        # 追问关键词检测
        followup_keywords = ["深入", "详细", "继续", "再说说", "具体"]
        compare_keywords = ["对比", "和上次", "上次的", "之前"]
        modify_keywords = ["改成", "换成", "调整为", "换成"]
        new_topic_keywords = ["换个", "新的", "另外"]
        
        for kw in followup_keywords:
            if kw in query:
                return Scenario.FOLLOWUP_DEEPEN
        
        for kw in compare_keywords:
            if kw in query:
                return Scenario.FOLLOWUP_COMPARE
        
        for kw in modify_keywords:
            if kw in query:
                return Scenario.FOLLOWUP_MODIFY
        
        # 检查是否新品类
        if any(kw in query for kw in new_topic_keywords):
            return Scenario.NEW_TOPIC
        
        # 如果上次意图相同且查询短，视为追问
        if last_intent and len(query) < 30:
            return Scenario.FOLLOWUP_DEEPEN
        
        return Scenario.NEW_QUERY

    def augment_query(query, scenario, working_memory) -> str:
        """根据场景增强查询"""
        if scenario == Scenario.FOLLOWUP_DEEPEN:
            last = working_memory.get_last_analysis()
            return f"{query}（上下文：上次分析了{last['category']}的{last['intent']}，关键发现：{last['key_findings']}）"
        
        if scenario == Scenario.FOLLOWUP_COMPARE:
            last = working_memory.get_last_analysis()
            return f"对比分析：当前查询'{query}'，上次分析：{last['query']}（结论：{last['key_findings']}）"
        
        if scenario == Scenario.FOLLOWUP_MODIFY:
            last = working_memory.get_last_analysis()
            return f"{query}（基于上次分析参数：{json.dumps(last['params'])}）"
        
        return query
```

**改动范围**：
- 新增 `backend/conversation.py`：ConversationManager
- agent_engine.py：Phase 1 意图识别前先调用 ConversationManager 做场景检测和查询增强

---

## 三、实现路线图

### Phase 0：准备（当前）

- [x] 架构设计文档（本文档）
- [ ] 创建 harness/ 目录结构
- [ ] 创建 config/dags.yaml

### Phase 1：Pipeline Harness（基础层）

```
实施顺序：
1. harness/__init__.py       ← 空壳
2. harness/registry.py        ← ToolRegistry（从 tools.py 迁移 AVAILABLE_TOOLS）
3. harness/dag_loader.py      ← DAGLoader（从 agent_engine.py 迁移 DAG_TEMPLATES → config/dags.yaml）
4. harness/executor.py        ← ParallelExecutor（改造 agent_engine._execute）
5. harness/tracer.py          ← TraceCollector（薄封装）
6. agent_engine.py refactor   ← 调用 harness 替代内联逻辑
```

**验证点**：Phase 1 完成后，跑一条选品用例，Console 输出不变，报告质量不变。

### Phase 2：CostRouter + 工作记忆（并行开发）

```
7. harness/router.py          ← CostRouter（复杂度判定 + DAG选择）
8. backend/conversation.py    ← ConversationManager（场景检测 + 查询增强）
9. memory.py 扩展             ← WorkingMemory（结构化上下文 + 分析历史）
10. agent_engine.py 集成      ← _llm_intent 前加路由判定，_build_context 改用 WorkingMemory
```

**验证点**：
- "帮我写法式茶歇裙淘宝标题" → Console 应跳过 trend_analyze/price_analyze/反思
- 连续两次相同品类查询 → 第二次报告应引用第一次的关键发现

### Phase 3：多轮对话

```
11. agent_engine.py 增强       ← Phase 1 前场景检测 + 查询增强
12. memory.py 持久化优化       ← session_chain 维护
```

**验证点**：
- "分析2026法式茶歇裙选品" → 得到报告
- "深入分析下价格" → 报告聚焦价格维度，引用上轮数据
- "和上次对比下" → 生成对比报告

### Phase 4：回归测试 + 端到端

```
13. 6类报告全链路测试（selection/competitive/trend/copy/pricing/launch）
14. 反思门控回归测试（低分重试 → 保留最高分）
15. PDF下载功能回归
16. 前端 Console 显示回归
```

---

## 四、风险控制

| 风险 | 缓解措施 |
|------|---------|
| 重构破坏现有功能 | 每个 Phase 完成后跑回归测试 |
| CostRouter 误判导致质量下降 | 先保守（低阈值），观察后调参 |
| 记忆累积污染上下文 | 工作记忆保持最近5条，不无限增长 |
| 并行执行引入竞态 | ParallelExecutor 纯函数式，无共享状态 |

---

## 五、验证 Checklist

```
□ Phase 1: 选品用例 Pipeline 输出不变
□ Phase 1: Console 六阶段展示不变
□ Phase 2: 文案查询跳过重工具（Console 显示 DAG 任务数 ≤ 3）
□ Phase 2: 连续两次同品类查询 → 第二次引用第一次结论
□ Phase 3: "深入分析" → 报告聚焦指定维度
□ Phase 3: "和上次对比" → 生成对比报告
□ Phase 4: 6 类报告全链路不退化
□ Phase 4: 反思门控 + PDF 下载正常
```
