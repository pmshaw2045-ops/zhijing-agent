# 织镜配置指南

> 本文档说明如何配置织镜以使用不同的 LLM Provider、搜索 API 和其他第三方服务。
> 织镜支持**任意 OpenAI 兼容 API**，不绑定任意供应商。

---

## 快速配置（新人 2 分钟上手）

```bash
# 1. 复制配置模板
cp .env.example .env

# 2. 编辑 .env，填入必要的 Key
#   核心依赖：LLM API（至少配这一个就能跑）
LLM_API_KEY=sk-your-key-here
```

其它选项（搜索、文生图）不配置也不会报错，系统会自动降级。

---

## LLM Provider 配置

### 核心变量

| 变量 | 是否必填 | 说明 | 示例 |
|------|---------|------|------|
| `LLM_API_KEY` | **是** | 你的 LLM API 密钥 | `sk-your-key` |
| `LLM_BASE_URL` | 否（有默认值） | API 端点地址 | `https://api.deepseek.com` |

### 模型分级（可选）

织镜内部将 LLM 任务分为三个等级，**普通用户只需配一个 API key，三个等级默认使用同一个模型**，无需逐个配置。

| 变量 | 默认值 | 用途 | 推荐模型 |
|------|--------|------|---------|
| `LLM_MODEL_FLASH` | `deepseek-chat` | 意图识别、工具提取（轻量快速任务） | DeepSeek V3 / GPT-4o-mini |
| `LLM_MODEL_PRO` | `deepseek-v4-pro` | DAG 拆解、质量审查（重量推理任务） | DeepSeek V4 / GPT-4o |
| `LLM_MODEL_CHAT` | `deepseek-chat` | 报告生成、反思（标准综合任务） | DeepSeek V3 / GPT-4o-mini |

按任务分级的好处：
- **省钱**：轻量任务用便宜的模型，重量任务用好模型
- **灵活**：可以根据预算和效果自由组合

### 配置示例

#### 使用 DeepSeek（默认推荐）

```env
LLM_API_KEY=sk-your-deepseek-key
LLM_BASE_URL=https://api.deepseek.com
```

#### 使用 OpenAI

```env
LLM_API_KEY=sk-your-openai-key
LLM_BASE_URL=https://api.openai.com/v1

# 按任务分级（可选，不配则全用同一个模型）
LLM_MODEL_FLASH=gpt-4o-mini
LLM_MODEL_PRO=gpt-4o
LLM_MODEL_CHAT=gpt-4o-mini
```

#### 使用自定义 OpenAI 兼容 API

```env
LLM_API_KEY=sk-your-api-key
LLM_BASE_URL=https://your-custom-endpoint.com/v1

LLM_MODEL_FLASH=your-fast-model
LLM_MODEL_PRO=your-reasoning-model
LLM_MODEL_CHAT=your-standard-model
```

### 向后兼容

旧配置 `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` **仍然生效**，无需手动迁移。如果新旧变量同时存在，`LLM_*` 优先。

```env
# 以下写法仍有效（旧用户无需改动）
DEEPSEEK_API_KEY=sk-your-deepseek-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

```env
# 推荐的新写法（新旧混用也没问题）
LLM_API_KEY=sk-your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

---

## 搜索 API 配置（可选）

搜索是数据源，**不配置也不会报错**——LLM 会基于自身知识生成分析，只是信息丰富度受影响。

| 变量 | 服务商 | 说明 |
|------|--------|------|
| `TAVILY_API_KEY` | Tavily（英文搜索） | 覆盖全球 web 搜索，适合时尚趋势等国际化内容 |
| `BOCHA_API_KEY` | 博查 AI（中文搜索） | 覆盖国内电商/新闻/百科，适合淘宝/抖音等 |

> 织镜使用 Tavily + 博查双引擎覆盖中英文搜索场景。
> 后续版本将支持配置化搜索引擎（`SEARCH_PROVIDER=tavily|bocha|serpapi|bing`）。

---

## 文生图配置（可选）

| 变量 | 服务商 | 说明 |
|------|--------|------|
| `ARK_API_KEY` | 豆包 Seedream（火山引擎） | 生成服装/模特图 |

不配置此 key 则文生图功能不可用，其余功能不受影响。

---

## 环境分层

织镜支持多环境配置：

```bash
# 开发环境（默认）
cp .env.example .env
APP_ENV=dev

# 预发布环境
cp .env.example .env.staging
APP_ENV=staging

# 生产环境
cp .env.example .env.prod
APP_ENV=production
```

加载优先级（高 → 低）：

```
1. os.environ（容器/云部署注入）
2. .env.{APP_ENV}（环境专属配置，覆盖基础值）
3. .env（项目根目录，所有环境共享）
4. ~/.hermes/.env（本地开发兜底）
```

---

## 配置诊断

启动织镜后，访问 `GET /api/health` 可查看当前配置状态：

```json
{
  "status": "ok",
  "llm": true,
  "models": {"flash": "deepseek-chat", "pro": "deepseek-v4-pro", "chat": "deepseek-chat"},
  "tavily": true,
  "bocha": false,
  "ark_image": false
}
```

或在终端执行诊断：

```bash
python3 -m backend.config
```

---

## 技术架构说明

织镜的配置系统基于 `backend/config.py`，设计要点：

- **分层加载**：`os.environ` → 项目 `.env` → `~/.hermes/.env`
- **向后兼容**：所有旧变量名（`DEEPSEEK_*`、`MODEL_*`）均保留为别名
- **Provider 无关**：核心变量名为 `LLM_*`，不绑定任意供应商
- **分级模型**：`flash/pro/chat` 三级，可分别配置不同模型
- **优雅降级**：搜索/文生图等可选服务无 key 时不崩溃

---

## 常见问题

**Q: 我只想快速看看效果，最少要配什么？**

A: 只配一个 `LLM_API_KEY` 就能跑。搜索和文生图都不需要。

**Q: 我有 DeepSeek 的 key，需要改配置格式吗？**

A: 不用。`DEEPSEEK_API_KEY` 仍然兼容，直接沿用旧 `.env` 即可。

**Q: 我想用 OpenAI 代替 DeepSeek，要改什么？**

A: 把 `.env` 改成：

```env
LLM_API_KEY=sk-your-openai-key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_FLASH=gpt-4o-mini
LLM_MODEL_PRO=gpt-4o
LLM_MODEL_CHAT=gpt-4o-mini
```

**Q: 为什么有三个模型等级？**

A: 这是架构层面的分级设计——轻量任务（意图识别）用快模型降低成本，重量任务（DAG 拆解/质量审查）用好模型保证效果。普通用户只配一个 key 也能跑，三个等级默认用同一个模型。
