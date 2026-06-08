# 织镜 ZHÌJÌNG — 架构审查报告

> 日期：2026-06-06
> 审查范围：后端 23 模块 / 3,892 行 + 前端 1,204 行
> 审查标准：扩展性、可维护性、职责清晰度、代码质量

---

## 一、总体评价

**等级：原型偏上，距生产级仍有差距。**

架构设计理念正确——Pipeline 模式、策略路由、IntentRegistry 集中元数据，这些在 Demo 阶段没有问题。但 4 个模块已经出现"负担过重"的信号，继续往上堆功能会越来越难维护。

---

## 二、逐模块审计

### 2.1 agent_engine.py（1050 行）⚠️ 最大风险

| 问题 | 严重度 |
|------|:--:|
| 1050 行单文件，mix 了 Pipeline 编排 + LLM 调用 + DAG 标准化 + 质量审查 + 记忆更新 | 🔴 |
| `_llm_decompose` 有三层标准化逻辑（dag 解包→字段名转换→nodes 转换）——补丁叠补丁 | 🔴 |
| `_build_decompose_prompt` / `_build_report_prompt` 等 5 个 prompt builder 全堆在一个类里 | 🟡 |
| `run_pipeline` 方法 200+ 行，8 个 Phase 全是 if/else | 🟡 |

**建议**：拆为 3 个文件：
- `agent_engine.py`：Pipeline 编排（~200行）
- `decompose.py`：DAG 拆解 + 标准化（~150行）
- `pipeline_phases.py`：Phase 6-7 报告+反思（~200行）

### 2.2 report.py（253 行）🟢 良好

策略路由 + JSON Schema 输出。6 个 `_prompt_xxx` 方法职责清晰。唯一问题：每个策略方法内的 HTML 示例是硬编码文本，换 JSON Schema 时需同时改前端——耦合未消除。

### 2.3 precheck.py（140 行）🟡 经历过 4 次重写

从黑名单→entity 驱动→兜底 fallback，每次都是因为 LLM 输出不可预测。最终三层防护方案可行，但 `_extract` + `_looks_like_product` 的组合仍依赖规则——50 个工具时维护成本会爬升。

### 2.4 memory.py（394 行）🟢 良好

五层记忆架构设计合理。唯一结构问题：`_store` 字典的直接操作散落在 30+ 处，改成 `get_session()`/`set_session()` 封装会大幅降低耦合。

### 2.5 tools.py（395 行）🟡 中等

8 个工具的定义+实现混在一个文件。建议按工具拆分或至少分组。
`execute_tool_sync` / `execute_tool_async` 两套接口——应统一为 async。

### 2.6 intent_registry.py（226 行）🟢 良好

Single Source of Truth 设计正确。7 个意图条目，每个含 9 个字段。新增意图只需加一个条目。**这是当前架构的亮点**。

### 2.7 frontend/index.html（1204 行）🔴 高风险

单文件混了 HTML + CSS + JS + 渲染引擎 + SSE 处理 + Console 面板。拆分成 3 个文件即可（已在计划中）。

---

## 三、6 类报告 Pipeline 评估

| 意图 | DAG 拆解 | 报告策略 | 前置校验 | 总体评价 |
|------|:--:|:--:|:--:|:--:|
| 选品分析 | LLM 自主 | 独立策略 | `require_analysis_object` | 🟢 |
| 竞品对标 | LLM 自主 | 独立策略 | `require_analysis_object` + `require_brands` | 🟢 |
| 趋势洞察 | LLM 自主 | 独立策略 | `require_analysis_object` | 🟢 |
| 文案生成 | LLM 自主 | 独立策略 | `require_analysis_object` | 🟡 (简单意图也走完整DAG, overhead) |
| 定价策略 | LLM 自主 | 独立策略 | `require_analysis_object` | 🟢 |
| 文生图 | 跳过(固定) | 固定模板 | `image_quality` | 🟢 |

**设计合理性**：✅ 每个意图独立策略、LLM 自主拆解、工具列表按意图过滤。  

**待优化**：
- 文案生成这类简单意图（3 种工具）走 8 Phase Pipeline 有点"杀鸡用牛刀"
- 文生图的 DAG 跳过逻辑是硬编码 `_FIXED_DAG_MODES`，应该在 registry 里声明 `skip_decompose: true`

---

## 四、长周期维护风险

| 风险 | 如果不管会怎样 | 建议 |
|------|------|------|
| agent_engine 继续膨胀 | 改一个 Phase 可能影响另一个，回归靠运气 | 拆分为 Pipeline + Decompose + Phases |
| precheck 规则堆叠 | 每次新增意图都要猜 LLM 会输出什么 | 换 LLM 驱动的 precheck（让 LLM 自判"信息是否充分"） |
| JSON 文件存储 | 会话 > 500 时写入延迟可感知 | SQLite 迁移（已在计划） |
| 前端单文件 | CSS 和 JS 的改动相互影响 | 拆分为 3 文件 |
| AGENTS.md 过时 | 记录的 DAG 结构还是旧版模板格式，与实际不符 | 更新文档 |

---

## 五、立即可做（低成本、高收益）

| # | 事项 | 投入 | 收益 |
|---|------|:--:|------|
| 1 | 更新 AGENTS.md | 30min | 文档与代码对齐 |
| 2 | agent_engine 拆 3 文件 | 2h | 降低后续改动风险 |
| 3 | memory.py 封装 `get_session()` | 1h | 减少直接 dict 操作 |
| 4 | 前端拆 3 文件 | 1h | CSS/JS 独立维护 |
| 5 | `_FIXED_DAG_MODES` → registry | 15min | 消除硬编码 |
