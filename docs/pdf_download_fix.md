# PDF 下载功能修复总结

> 日期：2026-06-09
> 涉及文件：`frontend/handler.js`

---

## 问题描述

点击报告区的「下载PDF」按钮后，新开的预览页面存在以下问题：

1. **打印窗口预览为空** — 新窗口打开后内容不可见，打印对话框预览空白
2. **报告底部内容被裁断** — 长报告的末尾部分（如竞品格局、TOP选品方向）缺失
3. **表格不铺满页面** — 竞品格局表格缩在左上角，未横向拉伸
4. **布局/样式丢失** — SWOT 单列、指标卡片无间距、颜色丢失
5. **下载按钮带入预览** — 聊天区的「下载PDF」按钮被复制到预览页

---

## 根因分析

### 根因一：`@media print` 规则误杀内容

`style.css` 的打印规则：

```css
@media print {
  body > *:not(.main) { display: none !important; }
}
```

新窗口的报告内容直接放在 `<body>` 下，没有 `.main` 包裹，所有报告组件（`.rc-metrics`、`.rc-swot` 等）都被 `display:none` 隐藏。

### 根因二：body CSS 溢出裁剪

`style.css` 定义：

```css
body { height: 100vh; display: flex; overflow: hidden; }
```

新窗口通过 `<link>` 加载此 CSS 后，`overflow:hidden` + `height:100vh` 将超出视口的报告内容全部裁剪。

### 根因三：`.msg-bubble` 上下文依赖

```css
.msg-bubble table { width: 100%; }
```

表格的 `width:100%` 样式被限定在 `.msg-bubble` 选择器下。新窗口没有此包裹元素，`<table>` 元素无显式宽度，缩在左上角。

### 根因四：`document.write` + `onload` 时序问题

最初使用 `document.write` + 跨窗口 `win.onload` 触发打印。`onload` 事件在不同浏览器/缓存条件下的行为不一致（CSS 缓存时可能错过），导致打印时机不可靠。

### 根因五：`innerHTML` 包含 UI 残留

下载按钮通过 `bubbleEl.appendChild(btn)` 追加到报告气泡内，`innerHTML` 提取时包含此按钮。

---

## 修复历程

| 轮次 | 问题 | 尝试方案 | 结果 |
|------|------|---------|------|
| 1 | 预览为空 | 存 `dataset.reportJson` + `renderReport` 重建 | 未解决 |
| 2 | 预览为空 | + `win.onload` 先绑再写 + 1s 兜底 | 未解决 |
| 3 | 预览为空 | Blob URL 替代 `document.write` | 未解决 |
| 4 | **定位到 CSS 错误隐藏** | 极简诊断版（无 CSS）、发现内容可见但无样式 | ✅ 发现根因 |
| 5 | 样式缺失 | 外包 `<div class="main">` 绕过 `@media print` | 部分解决 |
| 6 | 内容被裁断 | 内联 style 加 `!important` 覆盖 body 溢出 | 部分解决 |
| 7 | 表格不铺满 | `table{width:100%}` 全局规则 | 部分解决 |
| 8 | **自包含方案（最终）** | 完全内联所有报告 CSS，不依赖 `style.css` | ✅ 完全解决 |
| 9 | 按钮带入预览 | 从 `dataset.reportJson` 重建而非 `innerHTML` | ✅ 解决 |

---

## 最终方案

### 核心思路

预览页面**完全自包含**，不依赖 `style.css`。所有报告组件需要的 CSS 规则全部内联在 HTML 的 `<style>` 标签中。

### 数据流

```
聊天区报告渲染时
  → JSON 数据存入 bubbleEl.dataset.reportJson
  → renderReport(json) 渲染到聊天气泡

用户点击下载时（downloadPDF）
  1. 读 dataset.reportJson
  2. renderReport(JSON.parse(jsonStr)) 重建干净 HTML
  3. 拼接自包含 CSS（CSS变量 + 所有 .rc-* 规则 + 基础排版）
  4. window.open → document.write → document.close
  5. HTML 内 <script> 在 window.onload 后触发 win.print()
```

### 自包含 CSS 包含

- CSS 变量（`--accent-rose`, `--accent-gold` 等 20+ 个）
- 基础排版（h3/h4/p/ul/ol/li/table/th/td）
- 9 类报告组件样式：
  - `.rc-metrics` / `.rc-metric` — 指标卡片
  - `.rc-bar-chart` / `.rc-bar-row` / `.rc-bar-fill` — 条形图
  - `.rc-table` / `thead th` / `tbody td` — 数据表格
  - `.rc-compare` / `.rc-brand-card` — 品牌对比
  - `.rc-section-title` — 章节标题
  - `.rc-swot` / `.rc-swot-cell` — SWOT 四象限
  - `.rc-insight` — 提示块
  - `.rc-score-ring` — 评分环
  - `.rc-footer-note` — 页脚注
- `@page {size:A4; margin:20mm}` — 打印纸张
- `print-color-adjust: exact` — 颜色保真

### 不包含的内容（与 `style.css` 分离）

- 聊天布局：`.message`、`.msg-bubble`、`.msg-avatar`
- 页面框架：`.header`、`.console-panel`、`.chat-input-area`
- 打印规则中可能误杀内容的 `body > *:not(.main)` 选择器
- 任何 `overflow:hidden`、`height:100vh` 等布局副作用

---

## 改动文件

| 文件 | 改动内容 |
|------|---------|
| `frontend/handler.js` | 存储 `dataset.reportJson` + 重写 `downloadPDF`（~120 行内联 CSS + `renderReport` 重建 + `document.write` 写入） |
| `backend/server.py` | handler.js 响应头增加 `no-store, must-revalidate` 防缓存（仅 3 行） |

## 验证结果

- ✅ 打印预览内容完整（含指标、条形图、表格、SWOT、品牌对比）
- ✅ 表格横向铺满页面
- ✅ SWOT 双列布局
- ✅ 品牌色、卡片配色保留
- ✅ 无下载按钮等 UI 残留在预览页
- ✅ 自动弹出系统打印对话框
- ✅ 168 项单元测试全部通过，无回归
