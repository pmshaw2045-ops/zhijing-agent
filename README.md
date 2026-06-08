<p align="center">
  <h1 align="center">织镜 ZHÌJÌNG</h1>
  <p align="center"><em>服饰电商 AI Agent — 自然语言驱动的选品分析与竞品对标工具</em></p>
</p>

<p align="center">
  <a href="https://github.com/YOUR_USERNAME/fashion-agent-v2/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/tests-130%20passed-brightgreen.svg" alt="Tests">
  <img src="https://img.shields.io/badge/coverage-72%25-yellow.svg" alt="Coverage">
</p>

***

## 概述

织镜 ZHÌJÌNG 是一个面向**服饰电商**场景的 AI Agent 产品。输入自然语言描述（如"分析 2026 夏季法式茶歇裙的选品机会"），Agent 自动完成意图识别、DAG 任务拆解、多源搜索、LLM 分析、报告生成、质量审查的全流程。

后端**真实调用 DeepSeek LLM**，不是固定模板的伪 demo。

***

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/YOUR_USERNAME/fashion-agent-v2.git
cd fashion-agent-v2

# 2. 配置密钥
cp .env.example .env
# 编辑 .env 填入 DeepSeek/Tavily/博查 密钥

# 3. 安装依赖
pip install -r backend/requirements.txt

# 4. 启动
python3 -m uvicorn backend.server:app --host 0.0.0.0 --port 8899

# 5. 打开浏览器
open http://localhost:8899
```

### Docker

```bash
docker build -t zhijing .
docker run -p 8899:8899 --env-file .env zhijing
```

***

## 截图

> *TODO: 添加产品截图和演示 GIF。建议用:*
>
> - *选品分析报告展示（指标卡片 + 柱状图 + 表格）*
>
>   <br />
> - *Console 面板展示 Pipeline 实时状态*
> - *竞品对标 SWOT 矩阵*

***

## 架构

```
用户输入 → IntentRouter (意图识别, deepseek-chat)
         → PrecheckEngine (信息校验, 规则引擎)
         → DecomposeEngine (DAG 拆解, deepseek-v4-pro)
         → ParallelExecutor (并行执行, 30s 超时)
         → ReportBuilder (报告生成, deepseek-chat)
         → ReflectionEngine (质量审查, 7 分阈值)
         → SSE 流式返回
```

8 个 Phase Pipeline，每个 Phase 由独立引擎处理。所有意图元数据集中注册在 `IntentRegistry`，新增意图只需加一行配置。

***

## 功能

| 意图类型    | 说明                | 适用工具  |
| ------- | ----------------- | ----- |
| 单品选品分析  | 市场趋势 + 价格带 + 竞品格局 | 7 个工具 |
| 多品牌竞品对标 | 双品牌对比 + SWOT      | 4 个工具 |
| 品类趋势洞察  | 流行方向 + 面料/廓形/色彩   | 4 个工具 |
| 商品文案生成  | 淘宝/抖音/小红书文案       | 3 个工具 |
| 定价策略分析  | 价格分布 + 成本利润       | 5 个工具 |
| 上新排期建议  | 季节曲线 + 大促日历       | 3 个工具 |
| 文生图     | 豆包 Seedream 生成服装图 | 1 个工具 |

***

## 技术栈

| 层   | 选型                                          |
| --- | ------------------------------------------- |
| 后端  | Python 3.11 + FastAPI                       |
| LLM | DeepSeek v4-pro / chat                      |
| 文生图 | 豆包 Seedream 5.0                             |
| 搜索  | 博查 BochaAI（中文）+ Tavily（英文）                  |
| 前端  | 原生 HTML/CSS/JS（模块化：6 文件/100 行骨架）            |
| 存储  | JSON 文件（\~400 会话，SQLite 到规模再切换）             |
| 部署  | Docker + docker-compose + GitHub Actions CI |
| 测试  | pytest 130 项 + Jest 14 项，覆盖率 72%            |

***

## 项目结构

```
fashion-agent-v2/
├── AGENTS.md              项目主文档（AI Agent 入口）
├── backend/               28 模块 / 4,100+ 行
│   ├── agent_engine.py    Pipeline 编排
│   ├── intent_registry.py 意图元数据中心 (SSOT)
│   ├── memory.py          五层记忆系统
│   ├── tools.py           8 个工具实现
│   ├── decompose_engine.py DAG 自主拆解
│   ├── harness/           管道基础设施
│   └── ...
├── frontend/
│   ├── index.html         100 行 HTML 骨架
│   ├── style.css          CSS 设计系统
│   ├── render.js          报告渲染引擎 (9 种组件)
│   ├── sse.js             SSE 流式 + 重试
│   ├── handler.js         SSE 事件处理 + layout
│   └── console.js         Console 日志
├── tests/                 9 文件 / 130 项测试
├── docs/                  文档目录
│   ├── product_summary.md    产品与技术总结
│   ├── production_readiness.md  生产就绪度评估
│   ├── frontend_split_analysis.md  前端拆分分析
│   └── archive/              历史存档
└── .github/workflows/     CI (pytest + ruff)
```

***

## API

| 端点                                  | 说明                   |
| ----------------------------------- | -------------------- |
| `GET /`                             | 前端页面                 |
| `POST /api/chat`                    | SSE 流式对话（核心接口）       |
| `GET /api/health`                   | 健康检查                 |
| `GET /api/metrics`                  | Token 用量 / 请求统计      |
| `GET /api/memory/{id}`              | 会话记忆状态               |
| `GET /api/memory/{id}/conversation` | 会话历史                 |
| `GET /docs`                         | OpenAPI / Swagger 文档 |

详见 [AGENTS.md](AGENTS.md) 或直接访问 `http://localhost:8899/docs`。

***

## 协议

MIT License — 详见 [LICENSE](LICENSE)。
