# 织镜 ZHÌJÌNG — 工程级梳理报告

> 生成日期：2026-06-10
> 项目路径：`/Users/admin/zhijing-agent`
> 分支：`main`（HEAD -> origin/main）
> 模型：ark-code-latest (volcengine-coding-plan)

---

## 一、核心结论

1. 项目已经具备 **Agent 产品雏形 + 工程化测试兜底**，不是简单 ChatGPT 包壳。
2. 后端主链路清晰：FastAPI SSE → AgentEngine 8 阶段 Pipeline → IntentRegistry → LLM DAG 拆解 → ToolRegistry/ParallelExecutor → JSON 报告 → Reflection → Memory。
3. 当前自动化测试是健康的：
   - **后端单测**：176 passed, 1 skipped, 2 warnings
   - **前端 Jest**：57 passed
   - **后端业务代码 Ruff**：backend/ passed
4. **仍需修复的 P1 问题**：
   - Memory 异步索引 coroutine 未 await
   - 存储后端配置与文档不一致（JSON vs SQLite）
   - 前端 lint/format 脚本路径错误

---

## 二、已确认的项目规模

### 代码统计（pygount）

| 语言 | 文件数 | 代码行 | 说明 |
|:---|:---:|:---:|:---|
| Python | 41 | 4,332 | 后端核心 |
| HTML | 5 | 1,280 | 前端页面 |
| JavaScript | 10 | 1,098 | 前端逻辑 |
| CSS | 1 | 224 | 设计系统 |
| Markdown | 26 | — | 文档体系 |
| **总计** | **106** | **8,525** | |

### 后端模块清单

| 模块 | 行数 | 职责 |
|:---|:---:|:---|
| `agent_engine.py` | 506 | 核心编排引擎，8 阶段 Pipeline |
| `memory.py` | 620 | 五层记忆 + RAG 语义检索 |
| `tools.py` | 444 | 工具定义 + 搜索路由层 |
| `report.py` | 255 | JSON 报告生成器 |
| `intent_registry.py` | 243 | 意图元数据中心（SSOT） |
| `server.py` | 222 | FastAPI 应用入口 |
| `config.py` | 170 | 配置化 Provider |
| `llm_client.py` | 194 | LLM API 封装 |
| `intent.py` | 133 | IntentRouter |
| `conversation.py` | 247 | 多轮对话检测 |
| `auth.py` | 114 | 认证 + 速率限制 |
| `precheck.py` | 137 | 前置校验 |
| `decompose_engine.py` | 103 | DAG LLM 拆解 |
| `reflect.py` | 57 | 反思引擎 |
| `store.py` | 186 | SQLite 存储后端 |
| `observability.py` | 116 | 指标收集 |
| `harness/router.py` | 76 | CostRouter |
| `harness/executor.py` | 95 | ParallelExecutor |
| `harness/registry.py` | 83 | ToolRegistry |
| `harness/dag_loader.py` | 63 | DAG 模板加载器 |
| `harness/tracer.py` | 98 | 全链路追踪 |

### 前端模块

| 模块 | 行数 | 职责 |
|:---|:---:|:---|
| `index.html` | 109 | SPA 骨架 + 全局 state |
| `handler.js` | 566 | SSE 事件处理 + Console + PDF |
| `sse.js` | 150 | SSE 流式 + 重试 + sendMessage |
| `render.js` | 68 | 报告渲染引擎（9 种组件） |
| `console.js` | 25 | Console 日志系统 |
| `style.css` | 264 | CSS 设计系统 |
| `tests/` | 5 文件 | 57 passed |

---

## 三、后端架构认知

### 3.1 Agent Pipeline

```
Phase 0: 多轮对话检测       → conversation.py        → 规则引擎
Phase 1: LLM 意图识别       → intent.py              → deepseek-chat (flash)
Phase 2: 前置校验           → precheck.py            → 规则引擎（实体驱动）
Phase 3: DAG 任务拆解       → decompose_engine.py    → deepseek-v4-pro (pro)
Phase 4: 工具映射           → harness/registry.py    → ToolRegistry
Phase 5: 并行执行           → harness/executor.py    → ParallelExecutor
Phase 6: JSON 报告生成       → report.py              → deepseek-chat (chat)
Phase 7: 反思修正           → reflect.py             → 三维评分 < 7 重试（最多 2 次）
```

### 3.2 关键设计原则（已验证）

- **LLM 负责语义**：意图识别、DAG 拆解、报告生成、反思评分全部由 LLM 驱动
- **规则只做确定性事**：前置校验、工具映射、状态流转、速率限制
- **JSON Schema 渲染**：LLM 输出结构化 JSON，前端 9 种模板函数保障展示正确
- **IntentRegistry 集中元数据**：减少硬编码和跨文件的意图路由逻辑

### 3.3 意图类型与工具绑定

| 意图 | 可用工具数 | 前置校验 |
|:---|:---:|:---|
| 单品选品分析 | 7 | require_analysis_object |
| 多品牌竞品对标 | 4 | require_analysis_object + require_brands |
| 品类趋势洞察 | 4 | require_analysis_object |
| 商品文案生成 | 3 | require_analysis_object |
| 定价策略分析 | 5 | require_analysis_object |
| 上新排期优化 | 3 | require_analysis_object |
| 文生图 | 1 | image_quality |

### 3.4 记忆系统架构

| 层 | 内容 | 存储 | 注入格式 |
|:---|:---|:---:|:---:|
| L1 工作记忆 | 当前任务上下文 + intent + entities | SQLite | MD 摘要 |
| L2 短期记忆 | 滑动窗口 + 递归摘要 | SQLite | MD |
| L3 主题上下文 | 品类/品牌/季节/平台 | SQLite | MD |
| L4 分析历史 | 分析记录 → title 提取 | SQLite | MD |
| L5 长期记忆 | domains/brands/seasons/prefs | SQLite | MD |
| RAG 语义检索 | LLM embedding → SQLite 向量 | 余弦相似度 | 前三兜底 |

### 3.5 模型使用策略

| Phase | 模型 | 理由 |
|:---|:---|:---|
| Phase 1 意图识别 | deepseek-chat (V3) | 分类任务，低延迟 |
| Phase 3 DAG 拆解 | deepseek-v4-pro | 深度推理，2000 max_tokens |
| Phase 6 报告生成 | deepseek-chat (V3) | JSON 输出，速度优先 |
| Phase 7 反思修正 | deepseek-chat (V3) | 快速质检 |
| 工具层提取 | deepseek-chat (V3) | 结构化提取 |

---

## 四、前端架构认知

### 4.1 SSE 事件全表

| type | 说明 | 触发时机 |
|:---|:---|:---:|
| phase → running | 某阶段开始（含 model 标签） | 每个 Phase 入口 |
| phase → done | 某阶段完成（含数据摘要） | 每个 Phase 出口 |
| phase → step | 执行步骤级状态变更 | Phase 5 |
| clarify | 信息不足时回问用户 | Phase 2 |
| memory_search | 语义检索过程展示 | 报告前 |
| prompt | LLM 调用 Prompt 展示 | 每轮 LLM 调用 |
| result | 最终报告（JSON / HTML） | Phase 6 |
| quality_review | 质量审查区块 | Phase 7 |
| summary | Token/延迟/费用统计 | Pipeline 结束 |
| image_result | 文生图 URL | 图片生成完成 |
| history_comparison | 同类目历史对比 | 记忆检索命中 |
| done | Pipeline 完成 | 全部结束 |
| error | 执行错误 | 异常时 |

### 4.2 报告渲染链路

```
SSE result
  ↓ content 以 "{" 开头
JSON.parse
  ↓
renderReport(json)
  ↓ 遍历 sections
  └── metrics     → R.metrics()     → rc-metrics 布局
  └── bar_chart   → R.bar_chart()   → rc-bar-chart
  └── table       → R.table()       → rc-table
  └── brand_card  → R.brand_card()  → rc-brand-card
  └── compare     → R.compare()     → 双品牌对比
  └── swot        → R.swot()        → SWOT 矩阵
  └── insight     → R.insight()     → 洞察框
  └── section_title → R.section_title() → 分区标题
  └── text        → R.text()        → 纯文本
```

### 4.3 Console 架构

```
consoleOutput
  ├── pipelineContent (默认显示)
  │   ├── clog() 实时日志（按 tab 过滤）
  │   └── clogSection() 结构化区块（Prompt/Token统计/检索结果）
  └── memoryPanel (display:none)
      ├── 工作记忆
      ├── 主题上下文
      ├── 分析历史
      └── 对话记录
```

API 端点 | 方法 | 认证 | 用途
:---|:---:|:---:|:---
`/` | GET | ❌ | 前端页面
`/api/health` | GET | ❌ | 健康检查
`/api/chat` | POST | ✅ | SSE 流式对话
`/api/metrics` | GET | ❌ | 请求量/Token/延迟
`/api/memory/{id}` | GET | ❌ | 会话记忆
`/api/memory/{id}/conversation` | GET | ❌ | 会话历史

---

## 五、自动化检查结果

### 5.1 后端测试

- **命令**：`python3 -m pytest -q`
- **结果**：176 passed, 1 skipped, 2 warnings
- **耗时**：4.40s
- **关键警告**：
  ```
  RuntimeWarning: coroutine 'MemorySystem._index_analysis' was never awaited
  ```

### 5.2 前端测试

- **命令**：`npm test -- --runInBand`（在 `frontend/` 目录）
- **结果**：5 suites, 57 passed
- **耗时**：1.33s

### 5.3 Ruff Lint

| 范围 | 结果 | 说明 |
|:---|:---:|:---|
| `backend/` | All checks passed | ✅ |
| `tests/` | 10 errors | ❌ 主要在测试目录 |

### 5.4 前端 Lint

| 脚本 | 结果 | 说明 |
|:---|:---:|:---|
| `npm run lint` | ❌ | 路径错误：找 `frontend/frontend/` |
| `eslint .` | 342 warnings | 缺少浏览器/全局变量配置 |

### 5.5 前端 Format

| 脚本 | 结果 | 说明 |
|:---|:---:|:---|
| `npm run format:check` | ❌ | 路径错误 |
| `prettier --check` | 11 files | 未格式化 |
| `format:write` | 可修复 | |

### 5.6 配置诊断

| 配置项 | 文档声称 | 实际诊断 | 差异 |
|:---|:---:|:---:|:---:|
| `STORE_BACKEND` | SQLite 默认 | json | ⚠️ 需确认 |
| `APP_ENV` | 灵活配置 | dev | `.env` 文件中配了 production |
| `search_provider` | auto | auto | ✅ 一致 |
| 模型 | flash/pro/chat | deepseek-chat/v4-pro | ✅ |

---

## 六、风险清单（按优先级排序）

### P1 — 建议优先处理

1. **Memory 异步索引 coroutine 未 await**
   - 文件：`backend/memory.py:351-357`
   - 现象：`RuntimeWarning: coroutine was never awaited`
   - 根因：`record_analysis()` 是同步函数，用 `asyncio.create_task()` 但不在 running loop 内的场景会抛出 `RuntimeError`，被 `except Exception: pass` 吞掉
   - 影响：部分分析记录无法被向量化，前台无感知
   - 建议：先检查 `asyncio.get_running_loop()`，不存在时跳过并记录日志；恢复日志输出到 debug 级别

2. **存储后端配置与文档不一致**
   - 文件：`backend/config.py` / `.env` / 项目文档
   - 现象：文档强调 SQLite 默认，本地实际为 JSON；`.env` 中 `APP_ENV=production` 但诊断为 `dev`
   - 影响：排查记忆/RAG 问题时可能误判数据存储位置
   - 建议：明确当前默认值；`/api/health` 增加 `store_backend` 字段；同步 .env.example、README、AGENTS、docs

3. **前端 lint/format 脚本路径错误**
   - 文件：`frontend/package.json`
   - 现象：在 `frontend/` 目录下执行 `eslint frontend/` 会找 `frontend/frontend/`
   - 建议：修改为 `"lint": "eslint ."`，`"format:check": "prettier --check '**/*.{js,css,html}'"`
   - 注意：改脚本后需同步配置 ESLint globals（browser, jest, node）

### P2 — 中期治理

4. **Tests 目录 Ruff 未收敛**
   - 10 个错误（E401: 多 import 一行，E402: import 非文件顶部，F811: 重复导入，F821: 未定义变量）
   - 建议：明确策略 — 要么 CI 只 lint backend/，要么修复 tests 并纳入门禁

5. **handler.js 过重**
   - 当前 566 行，承担 SSE 分发、UI 事件、Memory 面板、PDF 导出、Console 标签管理
   - 建议后续拆分：`event_router.js`、`memory_panel.js`、`pdf_export.js`、`ui_events.js`

6. **ToolRegistry 静态注册**
   - 新增工具仍需改代码
   - 远期方向：工具 YAML 配置化 → MCP/Skills 协议

### P3 — 商业化/生产化

7. **数据源能力不足**
   - 当前仅依赖通用网页搜索，不具备精确定价/销量/SKU 数据
   - 建议优先接入：淘宝/天猫商品搜索 API、抖音电商数据源、小红书/趋势内容

8. **多租户与权限体系缺失**
   - 适合单用户 demo，不适合 SaaS
   - 需要：user_id/org_id、session ownership、memory 租户隔离、数据导出/删除

9. **Observability 仍是轻量版**
   - 无 trace_id 贯穿全链路、无结构化 JSON log、无告警机制、token 估算粗略

---

## 七、建议下一步执行顺序

| 阶段 | 事项 | 预估工时 | 价值 |
|:---|:---|---:|:---:|
| 阶段 1 | 修正 `memory.py` coroutine warning | 30min | 消除隐患 |
| 阶段 1 | 明确 `STORE_BACKEND` 默认值，统一文档 | 20min | 配置一致性 |
| 阶段 2 | 修 package.json lint/format 路径 | 15min | 工具链可用 |
| 阶段 2 | 配置 ESLint globals（browser/jest/node） | 30min | 质量门禁 |
| 阶段 2 | gradute handler.js 职责拆分 | 2h | 可维护性 |
| 阶段 3 | 报告 JSON schema 增加 source/confidence | 1h | 可信度 |
| 阶段 3 | quality_review 增加确定性检查 | 2h | 质量可度量 |
| 阶段 4 | 接入结构化电商数据源 | 专项 | 商业价值 |
| 阶段 4 | 工具注册配置化 | 专项 | 可扩展性 |
| 阶段 4 | 多租户与权限 | 专项 | SaaS 就绪 |

---

## 八、最终判断

当前织镜项目的定位：

| 场景 | 就绪度 | 判断依据 |
|:---|:---:|:---|
| 内部验证 / 作品集展示 | ✅ | 176 + 57 测试，backend lint 通过，Pipeline 完整 |
| 小范围外部 beta | ⚠️ 6/10 | 需先修 P1（异步 coroutine、配置一致性、前端工具链） |
| 正式商业 SaaS | ❌ 5/10 | 需数据源、多租户、观测、权限、部署体系 |
