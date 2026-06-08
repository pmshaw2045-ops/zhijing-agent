# 前端拆分技术分析

> 文档类型：评估报告（不推进，仅分析）
> 当前状态：`frontend/index.html` — 1,204 行单文件，HTML/CSS/JS 全部内联
> 历史教训：之前尝试过一次拆分 → 失败回退（原因：大爆炸式重构，3+ 文件联动）

---

## 一、当前代码结构

### 1.1 代码分区（1204 行）

| 行号 | 区域 | 行数 | 说明 |
|---|---|---|---|
| 1-6 | HTML 头部 | 6 | `<!DOCTYPE>`, `<meta>` |
| 7-331 | CSS (内联 `<style>`) | 325 | 设计系统（CSS 变量 + 组件样式） |
| 332-368 | Console 面板（JS） | 37 | `clog()`, `clogSection()`, `clearConsole()`, `filterByTab()` |
| 369-382 | Chat 界面（JS） | 14 | `addMessage()` |
| 383-404 | 状态管理（JS） | 22 | `STATUS_TEXT`, `updateStatus()` |
| 406-515 | API 调用层（JS） | 110 | `sendMessage()`, `sendMessageWithClarify()`, `_readSSEStream()`, `submitClarify()` |
| 516-586 | 报告渲染引擎（JS） | 71 | `R.{esc,metrics,bar_chart,table,brand_card,compare,swot,insight,section_title,text}`, `renderReport()` |
| 588-880 | SSE 事件处理（JS） | 293 | `handleSSEEvent()` — 最大单体函数 |
| 882-1080 | HTML 模板 (~199 行) | 199 | 页面布局 + 模态窗口 + Console 面板 |
| 1082-1204 | 辅助函数 + 事件绑定（JS） | 123 | `fixReportLayout()`, `injectDownloadBtn()`, `downloadPDF()`, 事件监听器 |

### 1.2 全局状态依赖

| 变量 | 类型 | 定义行 | 使用处 |
|---|---|---|---|
| `sessionId` | string | ~310 | sendMessage, API URL 拼接, Console 显示 |
| `currentMode` | string | ~310 | sendMessage, updateStatus, quickActions, sidebar |
| `isProcessing` | bool | ~310 | sendMessage, sendMessageWithClarify, 按钮状态 |
| `API_BASE` | string | ~310 | fetch URL 拼接 |
| `pendingSessionId` | string | 407 | submitClarify 回调传递 |
| `R` | object | 519 | renderReport, handleSSEEvent |
| `STATUS_TEXT` | object | 384 | updateStatus |

| DOM 元素 | 引用方式 | 使用处 |
|---|---|---|
| `userInput` | `getElementById` | sendMessage, 按钮事件 |
| `btnSend` | `getElementById` | sendMessage, 按钮事件 |
| `chatMessages` | `getElementById` | addMessage, sendMessage |
| `consoleOutput` | 全局变量 | clog, clogSection |
| `consolePanel` | `getElementById` | sidebarToggle, resize |
| `headerTitle` | `getElementById` | mode 切换 |
| `sessionsCount` | `getElementById` | loadSessionsCount |
| `knowledgeCount` | `getElementById` | loadKnowledgeCount |
| `memDisplay` | `getElementById` | handleSSEEvent (memory 显示) |
| `pipelineContent` | `getElementById` | clogSection, clearConsole |
| 模式按钮 | `querySelector` 批量 | mode 切换 |

### 1.3 函数调用链

```
sendMessage(text, mode)
  ├── userInput / btnSend / sessionId / currentMode
  ├── addMessage() → chatMessages
  ├── clearConsole()
  ├── clog()
  ├── fetch API_BASE + '/api/chat'
  ├── _readSSEStream(response, bubble)
  │     └── handleSSEEvent(event, bubble)
  │           ├── clog() / clogSection()
  │           ├── updateStatus() → STATUS_TEXT
  │           ├── R.renderReport() / fixReportLayout() / injectDownloadBtn()
  │           └── autoHighlightSidebar() → currentMode
  └── updateStatus()

sendMessageWithClarify(answer, sid)
  └── (同上，但带 clarify_answer 参数)
```

---

## 二、为什么上次拆分失败了（根因分析）

### 2.1 失败表现
- 拆成了 `sse.js + render.js + console.js + chat.js` 4 个文件
- 全局变量挂在 `window.xxx`
- 回退原因：功能全乱（CSS 互相影响、事件不触发、状态不同步）

### 2.2 真正的根因

**根因 #1：`handleSSEEvent` 是 293 行的"上帝函数"**
- 承担了 8 种 SSE 事件类型的分发逻辑
- 直接操作 DOM（`clog`、`updateStatus`、`bubble.innerHTML`）
- 耦合了 Console 面板、Chat 界面、状态管理的所有逻辑
- 任何拆分方案只要触及这个函数，就会变成大爆炸

**根因 #2：DOM 引用散落在 10+ 处**
- 不是通过一个 `App` 对象集中管理，而是 `document.getElementById` 散落在各处
- 拆成多文件后，每个文件独立拿 DOM，加载顺序决定生死

**根因 #3：隐式状态传递**
- `sessionId`、`currentMode`、`isProcessing` 都是裸全局变量
- `pendingSessionId` 通过闭包在 `submitClarify` → `sendMessageWithClarify` 间传递
- 没有任何"状态管理"的概念，纯依赖 JS 作用域

---

## 三、正确的拆分方案（绞杀者模式）

### 3.1 总体策略

**原则：逐模块替换、新旧共存、每步可验证。**

不拆 `handleSSEEvent`，而是用新模块**包裹**旧代码。每次只动一个模块。

```
Phase 1: 拆 CSS（0 风险）            → style.css (325行)
Phase 2: 拆 R 渲染引擎（低风险）        → render.js (71行)  
Phase 3: 拆 Console（中低风险）         → console.js (37行)
Phase 4: 拆 SSE 流式（中低风险）        → sse.js (110行)
Phase 5: 拆 handleSSEEvent（中风险）    → 拆为事件分发表 (293行→3层)
Phase 6: 引入 App 壳（低风险收尾）      → app.js (30行)
```

### 3.2 Phase 1：拆 CSS（5min，0 风险）

```
改动：7-331行 → 移到 frontend/style.css
index.html：保留 <link rel="stylesheet" href="/style.css">
验证：页面渲染完全一致（CSS 变量不变）
```

**风险**：无。只有路径变化，样式完全相同。

### 3.3 Phase 2：拆 R 渲染引擎（15min，极低风险）

```
改动：516-586行 → 移到 frontend/render.js
index.html：加 <script src="/render.js"></script>
验证：报告渲染 9 种组件类型全部正常
```

```
R 对象接口（纯函数，零 DOM 依赖）：
  R.esc(str) → str
  R.metrics(items) → HTML
  R.bar_chart(items) → HTML
  R.table(headers, rows) → HTML
  R.brand_card(name, rows, brand) → HTML
  R.compare(brands) → HTML
  R.swot(data) → HTML
  R.insight(style, title, body) → HTML
  R.section_title(text, style) → HTML
  R.text(content) → HTML
  renderReport(json) → HTML
```

**为什么风险极低**：R 对象的所有方法都是纯函数（输入→HTML 字符串），不依赖任何全局变量或 DOM，是最理想的拆分候选。

### 3.4 Phase 3：拆 Console（15min，中低风险）

```
改动：332-368行 → 移到 frontend/console.js
index.html：加 <script src="/console.js"></script>
```

```
Console 模块接口：
  clog(tag, text)           → 写入 consoleOutput
  clogSection(title, content) → 写入 pipelineContent
  clearConsole()            → 清空 pipelineContent
  filterByTab(tag, tab)     → 过滤逻辑
```

**依赖**：`consoleOutput` DOM 引用（从 index.html 传入）。

**解决 DOM 耦合**：Console 模块暴露一个 `initConsole(outputElement)` 方法，在 `index.html` 的 `<script>` 中调用一次。

### 3.5 Phase 4：拆 SSE 流式（20min，中低风险）

```
改动：406-515行 → 移到 frontend/sse.js
index.html：加 <script src="/sse.js"></script>
```

```
SSE 模块接口：
  _readSSEStream(response, reportBubble)  → 读取流 + 调用 handleSSEEvent
  sendMessage()                            → 主发送函数
  sendMessageWithClarify(answer, sid)      → 澄清发送
```

**依赖**：
- `API_BASE` — 传入参数
- `handleSSEEvent` — 仍在 index.html（Phase 5 才拆）
- `sessionId`, `currentMode`, `isProcessing`, `btnSend` — 通过 App 壳暴露

**关键设计**：这些函数接收一个 `config` 参数替代全局变量：

```javascript
// 之前
const response = await fetch(API_BASE + '/api/chat', ...);
// 之后
function createSSE(config) {
  return {
    async sendMessage(text, mode) {
      const resp = await fetch(config.apiBase + '/api/chat', {
        body: JSON.stringify({ message: text, session_id: config.sessionId, mode: config.mode })
      });
      await _readSSEStream(resp, config.reportBubble, config.onEvent);
    }
  };
}
```

### 3.6 Phase 5：重构 handleSSEEvent（60min，中风险）

**当前问题**：293 行单体函数，8 种事件类型全部混在一起。

**策略**：不是"拆分文件"，而是"分层重构"——将单一巨型函数变为事件分发 + 独立 handler。

```javascript
// 之前：293行 if/else if 嵌套
function handleSSEEvent(event, bubble) {
  if (type === 'phase' && status === 'running') { ... }
  else if (type === 'phase' && status === 'done') {
    if (phase === 'intent') { ... }
    else if (phase === 'decompose') { ... }
    else if (phase === 'router') { ... }
    // ... 6 种 else if
  }
  else if (type === 'result') { ... }
  else if (type === 'quality_review') { ... }
  // ... 4 种 else if
}

// 之后：事件分发表
const EVENT_HANDLERS = {
  'phase:running': handlePhaseRunning,
  'phase:done:intent': handleIntentDone,
  'phase:done:decompose': handleDecomposeDone,
  'phase:done:router': handleRouterDone,
  // ...
  'result': handleResult,
  'quality_review': handleQualityReview,
};

function handleSSEEvent(event, bubble) {
  const key = event.type === 'phase' && event.status === 'done'
    ? `phase:done:${event.phase}`
    : event.type === 'phase' && event.status === 'running'
    ? 'phase:running'
    : event.type;
  const handler = EVENT_HANDLERS[key];
  if (handler) handler(event, bubble);
}
```

**验证**：每种 SSE 事件类型的 Console 输出和 UI 表现与之前一致。

### 3.7 Phase 6：App 壳（15min，低风险收尾）

```javascript
// frontend/app.js (30行)
const App = {
  sessionId: generateSessionId(),
  currentMode: 'selection',
  apiBase: '',
  isProcessing: false,

  // DOM refs
  userInput: document.getElementById('userInput'),
  btnSend: document.getElementById('btnSend'),
  chatMessages: document.getElementById('chatMessages'),
  consoleOutput: document.getElementById('pipelineContent'),

  init() {
    initConsole(this.consoleOutput);
    this.bindEvents();
  },
  bindEvents() { /* 事件绑定统一管理 */ }
};

App.init();
```

---

## 四、server.py 同步改动

每个拆出的文件需要一个对应的 FastAPI 端点：

```python
# 已有
@app.get("/")            # index.html
@app.get("/style.css")   # CSS

# 新增
@app.get("/render.js")   # R 渲染引擎
@app.get("/console.js")  # Console 面板
@app.get("/sse.js")      # SSE API 层
@app.get("/app.js")      # App 壳（覆盖已删除的旧文件）
```

共 +4 个静态端点，每端点 3 行代码。

---

## 五、风险评估矩阵

| Phase | 涉及文件 | 风险等级 | 可单独回滚 | 验证方法 |
|---|---|---|---|---|
| 1 CSS | style.css (新增) | 🟢 极低 | ✅ | 视觉对比 |
| 2 R 渲染 | render.js (新增) | 🟢 极低 | ✅ | 9 种组件 + Jest 测试 |
| 3 Console | console.js (新增) | 🟡 中低 | ✅ | Console 面板四个 Tab |
| 4 SSE | sse.js (新增) | 🟡 中低 | ✅ | sendMessage 完整流程 |
| 5 Handler | index.html (修改) | 🟠 中 | ⚠️ 需 git tag | 7 种意图各跑一次 |
| 6 App 壳 | app.js (新增) | 🟢 低 | ✅ | 全局功能回归 |

**总耗时**：约 2.5h（6 Phase，每Phase独立可上线）

---

## 六、最终文件结构

```
frontend/
├── index.html      150行（HTML骨架 + App.init + 事件监听）
├── style.css       325行（CSS变量 + 组件样式）
├── render.js        71行（R 渲染引擎，纯函数）
├── console.js       37行（Console 日志系统）
├── sse.js          110行（SSE 流式 + 重试 + sendMessage）
├── app.js           30行（App 壳 + 全局状态 + DOM refs）
├── handler.js      150行（handleSSEEvent 分发表 + handler 函数）
├── layout.js       120行（fixReportLayout + injectDownloadBtn + downloadPDF）
├── tests/
│   ├── render.test.js   (已有)
│   └── setup.test.js    (已有)
```

index.html 从 1,204 行 → ~150 行（HTML 骨架），JS/CSS 全部模块化。

---

## 七、不建议的方案（主动排除）

1. **引入 Vite/Webpack** — 需要 npm + 构建配置，对 ~1200 行代码过度工程化
2. **React/Vue 重写** — 完全重写，当前风险/收益比不划算
3. **拆 handleSSEEvent 到多文件** — 上次失败就是这个方案。先拆其他模块，最后处理它
4. **引入 TypeScript** — 为 1200 行 JS 加 TS 配置，投入产出比低
