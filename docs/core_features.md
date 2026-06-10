# 织镜 ZHÌJÌNG — 面向 Agent 开发者的项目评估

> 作者视角：架构级编码实践者
> 目标读者：AI Agent 产品/架构开发者
> 用途：简历展示 / 技术评审 / 开源项目定位

---

## 一、架构亮点（Agent 开发者会关注的）

### 1.1 IntentRegistry — Single Source of Truth

7 种意图的所有元数据集中在 `intent_registry.py`：

```python
INTENT_REGISTRY = {
    "单品选品分析": {
        "mode": "selection",
        "complexity": Complexity.COMPLEX,
        "relevant_tools": ["bocha", "web", "trend", "price", "competitive", "scoring", "report"],
        "decompose_rule": "聚焦搜索趋势、价格段、竞品格局，避免全用工具",
        ...
    },
    ...
}
```

**为什么是好设计**：新加一个意图只需 10 行声明，无需改 Pipeline 代码。工具过滤、复杂度路由、DAG 拆解规则全部从 registry 推导，不硬编码。

### 1.2 LLM 自主 DAG 拆解（非 Workflow）

大多数 Agent 项目是套壳 Workflow——意图绑定固定任务流。织镜的工作方式是：

```
LLM 收到: intent_type + relevant_tools + decompose_rules
    ↓
自主设计: T1→bocha_search → T2→trend_analyze / T3→price_analyze / T4→competitive_analyze
    ↓  (parallel groups)
    → T5→report_generate
    ↓  (LLM 输出非 JSON 或无 tasks 字段时)
fallback: 注册在 registry 的默认模板
```

**价值**：同样的意图，用户问"分析价格"和"分析趋势"时，LLM 会产出不同的 DAG。静态模板兜底但不主导。

### 1.3 反射修正闭环

```
Phase 6 生成报告 → Phase 7 三维评分 (数据一致性/目标对齐/可落地性)
    ↓ overall < 7
第 1 次修正 → 重新评分
    ↓ overall 仍 < 7
第 2 次修正 → 取最高分版本
    ↓ 
质量审查 + 报告一起输出
```

**与同类项目的差异**：不是"一次生成就完事"，而是有质量门禁和自动修正。评分 < 7 时修正指令由 LLM 自动生成，不是固定 prompt。

### 1.4 Provider 无关的抽象层

| 层 | 抽象接口 | 实现选择 | 切换成本 |
|:---|:---|:---|---:|
| LLM | 任意 OpenAI 兼容 API | DeepSeek / GPT / 本地 | 改 1 行 config |
| 搜索 | `SEARCH_API_KEY` | Tavily / 博查 / 自定义 | 改 1 行 config |
| 存储 | `STORE_BACKEND` | SQLite / JSON | 改 1 行 env |

**不绑定任何厂商**——这是很多 Agent 项目忽略的。面试时能说清楚"为什么 Provider 无关比锁定某家更重要"是加分项。

### 1.5 三层记忆 + RAG 语义检索

```
L1-5 传统记忆架构 (CoALA 简化落地)
         └ 工作/滑动窗口/主题/分析历史/长期
L6 RAG 语义检索 (v2.1 新增)
         └ LLM embedding → SQLite 向量表 → 余弦相似度
             ↓ 失败
           同义词映射 (8 类目体系)
             ↓ 失败
           关键词匹配 (类目包含/意图精确)
```

**每层失败自动降级，不中断 Pipeline。** 这不是 demo 级设计——每条分析记录完成后异步 embedding + 向量化，不阻塞用户响应。

### 1.6 Console 透明化

每个 LLM 调用的 prompt、每个 Phase 的状态切换、每次语义检索的评分和来源——全部在 Console 面板实时可见。这不是调试工具，是产品的一部分：让用户信任 Agent 的决策过程。

---

## 二、技术债务与局限（诚实评估）

### 2.1 LLM embedding 一致性不足

直接调用通用对话模型（deepseek-chat）做 embedding，相同文本两次输出向量的余弦相似度仅 ~0.57。

**影响**：语义检索排序不可靠，实际依赖同义词映射 + 关键词匹配兜底。

**根因**：通用 LLM 不是为向量输出训练的。`embed_text` 通过 prompt hack 让模型输出 16 维浮点数组，但缺乏 `sentence-transformers` 或专用 embedding 模型的确定性。

### 2.2 无电商结构化数据源

当前数据来自通用网页搜索（Tavily + 博查），非结构化。缺少电商 API（如速 API）获取精确的价格/销量/评价数据。

**影响**：价格带分析和竞品分析依赖 LLM 自身知识，数据置信度有限。

### 2.3 单租户架构

- 无用户认证（仅 dev token）
- 会话数据按 session_id 隔离，无多用户权限控制
- 存储后端单文件（SQLite），水平扩展受限

### 2.4 工具注册硬编码

`AVAILABLE_TOOLS` 是 `tools.py` 顶部的静态列表，新增工具需改代码 + 重启服务。无运行时发现机制（如 Skills/MCP 协议）。

### 2.5 embedding 性能

每次 `embed_text` 调用 ~1.4 秒（LLM API 延迟），且无法 batch 处理。虽然用 `asyncio.create_task` 做了异步不阻塞，但向量存储是串行的。

---

## 三、中长期优化计划

### Phase 7 — 工具注册层抽象（P1, 2-4 周）

| 目标 | 做法 |
|:---|:---|
| YAML 配置化工具定义 | 每个工具一个 YAML 文件（name/desc/params/impl），`ToolRegistry` 启动时扫描目录加载 |
| 运行时热加载 | `watchdog` 监控工具目录，文件变化自动重载，无需重启 |
| 第三方工具包 | 支持 `pip install zhijing-tool-xxx` 后自动发现 |

**前置条件**：当前 `AVAILABLE_TOOLS` 已整合到 `ToolRegistry`，`DecomposeEngine` 已动态感知可用工具。

### Phase 8 — 电商数据源接入（P1, 2-3 周）

| 数据源 | 覆盖场景 |
|:---|:---|
| 速 API（淘宝/天猫） | 精确价格、销量、评价数、SKU分布 |
| 蝉妈妈 / 飞瓜（抖音） | 直播数据、达人选品、热销排行 |
| 官方趋势报告 | 权威面料/色彩趋势 |

**价值**：从"LLM 凭知识猜"到"真实数据说话"，置信度质变。同时可作为工具注册层落地的第一个真实用例。

### Phase 9 — 记忆系统升级（P2, 1-2 周）

替换 LLM embedding 为专用模型：

| 方案 | 成本 | 一致性 |
|:---|:---|---:|
| `sentence-transformers/all-MiniLM-L6-v2` | ~50MB, 零 API 成本 | 确定性的 |
| `text-embedding-3-small` (OpenAI) | API 调用, $0.02/1K tokens | 高一致性 |
| `bge-small-zh-v1.5` (BAAI) | ~30MB, 中文优化 | 确定性的 |

**选用标准**：一致性 > 准确率。当前 LLM hack 方式的最大问题不是向量质量，而是**每次调用结果不同**。

### Phase 10 — MCP 客户端接入（P3, 3-4 周）

| 能力 | 做法 |
|:---|:---|
| MCP 工具调用 | `mcp_connect` → 自动发现工具 → 注入 DecomposeEngine |
| MCP Agent 模式 | 子 Agent 通过 MCP 协议分发任务 |
| Skills 系统 | SKILL.md → 动态加载 → 意图扩展 |

### Phase 11 — 生产化（P3, 持续）

- **报告缓存 CDN**：当前 JSON 文件缓存，改为 Redis + TTL
- **多租户**：session_id → user_id + org_id 两层隔离
- **异步 worker**：Pipeline 可拆为 `队列 → worker → 回调`，解耦 HTTP 连接生命周期
- **全异步化**：当前 `tools.py` 仍用同步 `chat_sync` + `asyncio.to_thread`，改为原生异步

---

## 四、一句话总结

> **织镜是一个"认真对待 Agent 架构"的项目。** 
> 不是套壳 ChatGPT，不是固定 Workflow，是一个从真实需求出发、有反思闭环、有 Provider 抽象、有透明 Console、有 233 测试兜底的纺织电商 AI Agent。
> 
> 它的架构设计文档和代码实现之间的差距很小——这在 Agent 开源项目中不多见。

---

## 五、附录：Agent 项目横向对比

| 维度 | 织镜 | 典型 Agent SDK | 典型 Hackathon 项目 |
|:---|:---:|:---:|:---:|
| LLM 自主 DAG | ✅ | ❌（固定 Workflow） | ❌ |
| 反射修正闭环 | ✅ | ❌ | ❌ |
| Provider 无关 | ✅ | ⚠️（半绑定） | ❌ |
| 测试覆盖 | 233 项/76% | ⚠️ | 0-10 项 |
| 文档完备 | 5 文档 | ✅ | ❌ |
| Console 透明 | ✅ | ❌ | ❌ |
| 三层检索兜底 | ✅ | ❌ | ❌ |
| CI/CD | GitHub Actions | ✅ | ❌ |
| 零新依赖向量检索 | ✅ | ❌（需 FAISS/Chroma） | ❌ |
| 生产级部署 | ⚠️（单租户） | ✅ | ❌ |
