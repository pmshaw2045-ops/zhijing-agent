# PRD — 织镜 ZHÌJÌNG v1.0

> 产品经理：PM角色 | 版本：v1.0 | 日期：2026-06-04

---

## 一、产品定位

面向服饰类电商商家的AI Agent工作台。一句话描述：**自然语言驱动的选品分析与竞品对标工具**。

与现有demo的核心差异：**后端真实调用DeepSeek大模型完成意图识别、任务拆解、报告生成，前端只做展示和交互**。

## 二、核心功能 (v1.0 MVP)

### F1: 智能选品分析
- 输入：NL描述（品类+风格+时间+预算）
- 输出：结构化选品报告（市场热度/价格带/竞争格局/TOP5推荐方向/避坑建议）
- 模型链路：flash意图识别 → pro DAG拆解 → flash+规则 工具映射 → pro 报告生成

### F2: 竞品对标分析
- 输入：NL描述 + 指定品牌（可自动补全Top3）
- 输出：多维度竞品分析报告（定位/产品矩阵/价格带/面料/营销/渠道/SWOT）
- 复用 fashion-agent 参考文件的分析框架

### F3: 趋势洞察
- 输入：NL描述（品类+时间）
- 输出：当季趋势方向+热度排序+选品建议

### F4: Console Pipeline可视化
- 实时SSE流展示6阶段执行过程
- 每阶段标注模型选择（flash/pro）
- FSM状态流转可视化
- 记忆写入日志

## 三、技术规格

| 维度 | 规格 |
|------|------|
| 后端框架 | Python FastAPI + uvicorn |
| LLM Provider | DeepSeek API (openai兼容) |
| 轻量模型 | deepseek-v4-flash |
| 重量模型 | deepseek-v4-pro |
| 通信方式 | SSE (Server-Sent Events) |
| 记忆持久化 | JSON文件 (data/memory_store.json) |
| 前端 | 原生HTML/CSS/JS SPA，无框架依赖 |
| 端口 | 8899 |

## 四、Pipeline详细设计

### Phase 1: 意图识别 (flash, ~0.3s)
```
System: "你是服饰电商意图识别专家。从用户输入中提取结构化意图..."
User: "帮我分析2026夏季法式茶歇裙"
Output: JSON { intent_type, entities:{ subject, category, style, time, brands, platforms }, confidence }
```

### Phase 2: 前置校验 (规则引擎, ~0.01s)
- 4维度并行校验：信息完整性/权限/合规/依赖
- 输出缺口列表 + 补全策略 + 置信度矩阵

### Phase 3: DAG任务拆解 (pro, ~1.5s)
```
System: "你是任务规划专家。将用户目标拆解为可执行的DAG任务流。每个任务必须单一职责、绑定工具..."
User: Goal + 前置校验结果
Output: JSON { tasks:[{id, desc, tool, deps, layer}], dag_valid, parallel_groups }
```

### Phase 4: 工具映射 (规则+flash, ~0.3s)
- 规则引擎：工具Schema匹配
- LLM：参数槽位填充

### Phase 5: 执行调度 (执行引擎, ~2-5s)
- 真实web_search调用
- FSM状态机驱动
- 结果聚合

### Phase 6: 反思修正 (flash, ~0.5s)
- 格式校验 + 数据合理性 + Goal对齐检查
- 不合格则触发重规划

## 五、UI/UX规格

- 三栏布局：侧边栏(模式切换) | 对话区 | Console
- 配色：暖香槟色系(与demo一致)
- Console深色终端风格
- SSE流式更新，每阶段实时推送
- 快速入口按钮(6个)

## 六、验收标准

1. ✅ 输入"2026夏季法式茶歇裙选品" → 返回真实LLM生成的选品报告
2. ✅ 输入"太平鸟vs伊芙丽竞品分析" → 返回竞品对标报告
3. ✅ Console面板实时展示完整Pipeline(含模型标注)
4. ✅ 记忆系统跨会话保留上下文
5. ✅ 两次相同意图的请求，输出不完全相同(证明是LLM实时生成)
6. ✅ 错误处理：LLM调用失败时有graceful降级
