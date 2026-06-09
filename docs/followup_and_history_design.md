# 多轮追问优化 + 分析历史趋势 — 技术设计

> 日期：2026-06-08
> 目标：提升织镜 Agent 的多轮对话能力和分析历史回溯能力
> 影响范围：`conversation.py` / `agent_engine.py` / `memory.py` / `frontend/handler.js`

---

## 一、多轮追问优化

### 1.1 现状问题

当前 `conversation.py` 的多轮场景检测依赖关键词匹配 + 文本拼接增强，存在两个核心缺陷：

| 场景 | 用户输入 | 当前行为 | 期望行为 |
|:---|:---|:---|:---|
| 实体替换 | "那泡泡袖呢" | 关键词不命中 → NEW_QUERY → 重新跑全流程，丢失上下文 | 提取"泡泡袖" → 替换旧 goal 中的品类字段 → 保持原意图重新执行 |
| 隐式深入 | "详细说说" | FOLLOWUP_DEEPEN → 文本拼接 `[上下文：...]` | 同上，但需要保留原 goal 所有字段 |
| 意图切换 | "换成品类趋势" | 可能命中 FOLLOWUP_MODIFY → 但只拼接文本，不改变意图类型 | 识别意图切换意图 → 修改 intent_type |

### 1.2 方案：实体提取 + 结构化 goal 合并

**不再使用文本拼接 `[上下文：...]` 方式，改为直接修改 intent.goal 的结构化字段。**

#### 1.2.1 实体提取（规则 + LLM 兜底）

```python
def extract_entities_from_followup(query: str, last_intent: dict) -> dict:
    """
    从追问中提取新实体，返回需要修改的 goal 字段映射。

    纯规则层（正则匹配常见句式）:
      "那泡泡袖呢" / "那泡泡袖怎么样"  →  {"品类": "泡泡袖"}
      "换成夏装" / "改夏季连衣裙"       →  {"品类": "夏装"}
      "对比伊芙丽"                      →  {"竞品品牌": ["伊芙丽"]}
      "换成品类趋势分析"                →  {"intent_type": "品类趋势洞察"}
      "不要蕾丝"                        →  {"风格": 移除"蕾丝"}
      "追加泡泡袖"                      →  {"品类": 追加"泡泡袖"}

    LLM 兜底层（规则未命中时）:
      调用 flash 模型提取实体，给定上次 goal 结构，输出 JSON 变更
    """
```

**规则优先级**：正则句式 > 提取词槽 > LLM 兜底 > 不修改（兜底不做比做错好）

#### 1.2.2 结构化 goal 合并

```python
def merge_goal(last_goal: dict, changes: dict) -> dict:
    """
    将提取的变更合并到旧 goal，生成新 goal。

    规则:
      - 标量字段（品类/风格/时间）直接替换
      - 列表字段（竞品品牌）追加而非替换
      - 未提及的字段保持原值
      - 不兼容字段自动清空（如换意图类型时清空旧 goal 字段）
    """
```

#### 1.2.3 LLM 场景兜底

```python
def detect_scenario_llm(query: str, last_intent_type: str, last_goal: dict) -> str:
    """
    keyword scan 未命中时调用。flash 模型，低 token 消耗。

    prompt:
      用户上次意图: {last_intent_type}
      用户上次目标: {last_goal}
      当前输入: {query}
      
      判断属于哪种场景并只输出场景名:
      - new_query
      - followup_deepen
      - followup_compare
      - followup_modify
      - new_topic
    """
```

#### 1.2.4 Phase 0 数据流变更

```
当前:
  detect_scenario(keyword) → augment_query(text bracket) → LLM 自己理解

改后:
  detect_scenario(keyword + LLM fallback) → extract_entities → merge_goal
                                                              ↓
                                                         修改 intent.goal
                                                              ↓
                                                         LLM 看到的结构化 goal 已经正确
```

### 1.3 不改的

- `detect_scenario()` 的关键词排查逻辑保持不变（只在未命中时加 LLM 兜底）
- `augment_query()` 保留但不再被 Phase 0 调用（转为备用药）
- SSE 事件结构不变（前端无感）

---

## 二、分析历史趋势

### 2.1 现状问题

当前 `memory.record_analysis()` 存储了近 5 条历史分析记录，但存在两个空缺：

| 问题 | 影响 |
|:---|:---|
| LLM 报告生成时不参考历史 | 用户问两次"法式茶歇裙"，第二份报告不参考第一份的结论 |
| 前端无对比展示 | 用户无法直观看到「这次分析 vs 上次分析」的变化 |

### 2.2 方案：历史注入 + SSE 对比事件

#### 2.2.1 同类目历史检索

```python
# memory.py 新增
def find_related_analyses(self, session_id: str, category: str) -> list[dict]:
    """
    从 analysis_history 中检索同类目的历史分析记录。
    按时间倒序返回，最多 3 条，排除当前这次。
    """
```

#### 2.2.2 报告生成阶段注入历史

`agent_engine.py` Phase 6（报告生成）前增加一步：

```python
# 报告生成 prompt 中追加历史趋势
related = self.memory.find_related_analyses(session_id, category)
if related:
    history_context = format_history_context(related)
    # 注入到 report prompt 中
    report_prompt += f"\n\n【历史分析参考】\n{history_context}"
```

注入格式以自然语言描述，不暴露 JSON 结构。例如：

```
【历史分析参考】
您此前对"法式茶歇裙"做过分析（2026-06-07）：
- 核心结论：法式茶歇裙为高增长·中度竞争·强季节性品类
- 关键数据：搜索热度82，价格带¥150-350，目标毛利率55-65%
- 建议：推荐方领+泡泡袖+A字中长裙，天丝/醋酸面料
```

#### 2.2.3 SSE 历史对比事件

报告生成完成后，额外发送一个 SSE 事件给前端：

```python
yield {
    "type": "history_comparison",
    "data": {
        "current": {"title": ..., "summary": ..., "intent": ...},
        "previous": [{"title": ..., "summary": ..., "timestamp": ...}, ...]
    }
}
```

#### 2.2.4 前端展示

`handler.js` 新增 `history_comparison` 事件处理：

```javascript
// 在报告下方的对话气泡中追加一个「历史分析对比」区块
// 显示当前报告摘要 + 以前报告摘要的对照列表
// 纯文本展示，不改渲染引擎
```

---

## 三、影响范围总表

| 文件 | 改动类型 | 行数预估 | 风险 |
|:---|:---|:---:|:---:|
| `conversation.py` | 新增方法 | +60 | 低 |
| `agent_engine.py` | Phase 0 + Phase 6 各加几行 | +25 | 中 |
| `memory.py` | 新增查询方法 | +20 | 低 |
| `frontend/handler.js` | 新增 SSE 事件分支 | +15 | 低 |
| `tests/test_conversation.py` | 新增测试 | +80 | 低 |
| `tests/test_memory.py` | 新增测试（可选） | +30 | 低 |

**不改的**：tools.py / decompose_engine.py / server.py / intent.py / render.js / console.js

---

## 四、验收标准

### 多轮追问

1. ✅ "那泡泡袖呢" → 品类替换为泡泡袖，保持选择品意图重新执行
2. ✅ "详细说说" → 保留原 goal，要求 LLM 深入分析
3. ✅ "对比伊芙丽" → 竞品品牌追加伊芙丽
4. ✅ "换成品类趋势" → 意图切换为品类趋势洞察
5. ✅ 纯新查询 → 不受影响，正常走 NEW_QUERY

### 分析历史趋势

6. ✅ 新报告的 prompt 包含同类目历史分析的 key_findings
7. ✅ 前端收到 history_comparison SSE 事件
8. ✅ 前端对话气泡中显示历史对比区块
