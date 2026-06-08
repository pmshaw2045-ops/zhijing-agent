# 织镜工具注册层抽象设计

> 为 Skills（技能系统）和 MCP（Model Context Protocol）提供统一的工具注册基础。
> 本文档只做设计，不动代码。

---

## 1. 现状分析

### 1.1 当前工具注册链路

```
tools.py:28-37  AVAILABLE_TOOLS = [...]       ← 硬编码列表
                     ↓
agent_engine.py:504  tool_names = [t["name"] for t in AVAILABLE_TOOLS]
                     ↓
                     LLM 拆解时参考工具名生成 DAG
                     ↓
tools.py:42-54  execute_tool(name)            ← if/elif 硬路由
```

### 1.2 关键痛点

| 痛点 | 位置 | 问题 |
|------|------|------|
| 工具列表硬编码 | `tools.py:28` | 加工具必须改源码，无法热插拔 |
| 执行路由硬编码 | `tools.py:42` | `if name == "web_search"` 无法路由到外部工具 |
| 描述耦合 | `AVAILABLE_TOOLS` 的 description | LLM 看到的工具描述和实际调用耦合在一起 |
| 无发现机制 | 无运行时发现 API | 前端/MCP 无从知道当前 Agent 有什么工具 |
| 无隔离域 | 所有工具共享全局 namespace | Skills 之间可能有同名工具冲突 |

### 1.3 为什么现在不改

当前状态对单体开发够用。这份文档是为了**在需要扩展时能快速落地**，不阻塞业务迭代。

---

## 2. 设计目标

```
统一注册中心          ← Skills、MCP、本地工具都注册到这里
    ↓
声明式发现            ← LLM/前端通过统一接口知道「有什么工具」
    ↓
动态路由              ← 执行时根据注册信息路由到正确的实现
    ↓
隔离沙箱              ← 每个工具有独立的配置域
```

### 2.1 具体目标

1. **一刀不砍现有代码** — `_tavily_search()` 等具体实现函数不改
2. **增量引入** — 可以先注册现有工具，再逐步加 Skills/MCP
3. **运行时增删** — 支持在进程运行时加载/卸载工具（热插拔）
4. **来源透明** — LLM 不需要知道工具来自本地、Skills 还是 MCP
5. **名称空间隔离** — 不同来源的工具不会互相覆盖

---

## 3. 数据模型

### 3.1 统一工具描述

```python
@dataclass
class ToolDef:
    """统一工具定义 — 不论来源是本地/Skills/MCP"""
    name: str                     # 工具名，全局唯一
    description: str              # LLM 看到的描述
    parameters: dict[str, Any]    # JSON Schema 格式的参数声明
    source: str                   # "local" | "skill" | "mcp"
    source_id: str | None = None  # 来源 ID（skill 名 / mcp server 名）
    handler: Callable | None = None    # 本地/Skill 的执行函数
    mcp_server: str | None = None      # MCP server 标识
    config: dict[str, Any] | None = None  # 工具级配置
```

### 3.2 注册中心

```python
class ToolRegistry:
    """
    全局工具注册中心 — 所有工具的唯一 SSOT。

    职责:
      - 接收来自不同来源的工具注册
      - 维护全局工具列表（供 LLM 拆解参考）
      - 路由执行请求到正确的 handler
      - 提供运行时发现接口（前端 / MCP 通用）
    """

    def register(self, tool: ToolDef) -> None:
        """注册一个工具，同名覆盖（同 source 时）"""

    def unregister(self, name: str, source: str) -> bool:
        """注销一个工具"""

    def get_tool(self, name: str) -> ToolDef | None:
        """根据名称查找工具"""

    def list_tools(self, source: str | None = None) -> list[ToolDef]:
        """列出全部工具，可选按来源过滤"""

    def execute(self, name: str, params: dict) -> Any:
        """执行一个工具（路由到对应 handler）"""
```

---

## 4. 三层注册来源

### 4.1 Layer 1: 本地工具（现有）

```python
# tool_registry.py 初始化时自动注册

registry.register(ToolDef(
    name="web_search",
    description="Web搜索(英文/全球)",
    parameters={"query": {"type": "string", "description": "搜索关键词"}},
    source="local",
    handler=_search  # 或 _search_sync
))

registry.register(ToolDef(
    name="bocha_search",
    description="Web搜索(中文/电商)",
    parameters={"query": {"type": "string", "description": "搜索关键词"}},
    source="local",
    handler=_search
))

# ... trend_analyze, price_analyze, etc.
```

**存量兼容**：`AVAILABLE_TOOLS` 常量改为 `registry.list_tools()` 动态构建，所有引用处不改。

### 4.2 Layer 2: Skills（技能包）

```
skills/
  fashion-trends/             ← skill 目录
    SKILL.md                  ← 声明文件（工具定义 + prompt）
    handler.py                ← 执行逻辑
    assets/                   ← 依赖资源

  competitor-analysis/
    SKILL.md
    handler.py
```

**SKILL.md 示例**：

```yaml
name: fashion-trends
version: 1.0.0
description: 服饰趋势分析技能
tools:
  - name: trend_forecast
    description: 基于历史数据预测下季趋势方向
    parameters:
      category: { type: "string", description: "类目" }
      season: { type: "string", description: "季节" }
dependencies:
  - numpy
  - pandas
```

**加载方式**：`SkillLoader` 扫描 `skills/` 目录，解析 SKILL.md，动态注册。

```python
class SkillLoader:
    def load_skill(self, path: Path) -> list[ToolDef]:
        """加载一个 skill 目录，返回其提供的工具列表"""

    def load_all(self, base_path: Path) -> list[ToolDef]:
        """加载全部 skill"""

    def unload(self, skill_name: str) -> None:
        """卸载一个 skill（注销其所有工具）"""
```

### 4.3 Layer 3: MCP（外部工具协议）

```python
class MCPBridge:
    """
    将 MCP server 的工具桥接到 ToolRegistry。

    工作流:
      1. 连接 MCP server（stdio / HTTP）
      2. 调用 tools/list 获取工具列表
      3. 为每个工具创建 ToolDef（handler → 调用 tools/call）
      4. 注册到 ToolRegistry
      5. 监听 server 事件（工具列表变更时更新注册）
    """

    def connect_stdio(self, command: str, args: list[str]) -> None: ...
    def connect_http(self, url: str, headers: dict) -> None: ...
    def disconnect(self, server_id: str) -> None: ...
```

**MCP server 配置**（`config.yaml`）：

```yaml
mcp_servers:
  filesystem:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
  web-search:
    url: "http://localhost:8080/mcp"
```

---

## 5. 核心变更点

### 5.1 `tools.py` 的退化

```
改前: AVAILABLE_TOOLS + if/elif + 具体函数
改后: 只保留具体函数实现，注册和路由交由 ToolRegistry
```

具体：

```python
# tools.py 最终形态
from tool_registry import registry

# 只在模块加载时注册一次（或延迟注册）
registry.register(ToolDef(
    name="web_search", handler=_search,
    source="local", ...
))
registry.register(ToolDef(
    name="bocha_search", handler=_search,
    source="local", ...
))
# ... 其他工具

# AVAILABLE_TOOLS 改为动态生成
AVAILABLE_TOOLS = lambda: registry.list_tools()  # 或 property

# execute_tool / execute_tool_sync 改为委托
async def execute_tool(name, params):
    return await registry.execute(name, params)
```

### 5.2 `agent_engine.py` 的改动

```python
# 改前
tool_names = [t["name"] for t in AVAILABLE_TOOLS]

# 改后（接口不变）
tool_names = [t.name for t in registry.list_tools()]
```

### 5.3 新增文件

```
backend/
  tool_registry.py      ← 注册中心 + ToolDef
  skill_loader.py       ← Skills 加载器
  mcp_bridge.py         ← MCP 桥接
```

### 5.4 不动文件

```
backend/agent_engine.py    ← 只改 1 行引用
backend/decompose_engine.py ← 不改
backend/config.py          ← 不改
frontend/*                 ← 不改
tests/*                    ← 不改（新增 registry 测试即可）
```

---

## 6. 数据流对比

### 当前

```
LLM → decompose_engine → ["web_search", "trend_analyze"]
                           ↓
                    execute_tool("web_search", {query: ...})
                           ↓
                    if name == "web_search" → _tavily_search()
```

### 改后

```
LLM → decompose_engine → ["web_search", "trend_analyze"]
                           ↓
                    registry.list_tools()  ← 包含 local + skills + mcp
                           ↓
                    registry.execute("web_search", {query: ...})
                           ↓
                    ToolDef.source == "local" → _search()
                    ToolDef.source == "skill" → skill.handler()
                    ToolDef.source == "mcp"   → mcp_bridge.call()
```

---

## 7. 发现接口

### 7.1 新增 API 端点

```
GET /api/tools
  返回: 全部已注册工具（含描述 + 参数 schema）
  用途: 前端展示 / MCP 服务端 / 调试

POST /api/tools/execute
  参数: { name: "web_search", params: { query: "..." } }
  返回: 执行结果
  用途: 临时测试 / 外部调用

GET /api/tools/sources
  返回: 当前注册来源列表（local / skills / mcp）
```

### 7.2 MCP 兼容

`GET /api/tools` 的输出格式可以直接映射到 MCP 的 `tools/list` 响应，使得织镜自身也可以作为一个 MCP server 被其他 Agent 消费。

---

## 8. 迁移路径

### Step 1: 新增 `tool_registry.py`（纯新代码）

- 实现 `ToolDef` / `ToolRegistry` / `register()` / `execute()`
- `AVAILABLE_TOOLS` 改为由 registry 生成
- `execute_tool` 改为委托 registry
- 现有工具逐个注册到 registry

**验证**：所有现有测试通过，功能零变化。

### Step 2: 新增 Skills（纯新代码）

- 实现 `SkillLoader`
- 定义 SKILL.md 格式
- Skills 注册到 registry

**验证**：注册后工具列表扩大，LLM 可选择使用。

### Step 3: 新增 MCP（纯新代码）

- 实现 `MCPBridge`
- 支持 stdio / HTTP 连接
- MCP 工具注册到 registry

**验证**：MCP server 连接后工具可见可调用。

---

## 9. 边界情况

| 场景 | 策略 |
|------|------|
| 同名工具来自不同来源 | 按优先级：local > skill > mcp；或 source name 做 namespace |
| 工具执行超时 | registry.execute 设超时兜底（继承现有 30s 超时） |
| MCP server 断连 | registry 标记为不可用，LLM 拆解时排除 |
| Skill 加载失败 | 单个 Skill 失败不影响其他，抛警告不抛错误 |
| 循环依赖 | Skills 之间不允许互相依赖（每个 Skill 独立） |

---

## 10. 不做的事

- ❌ 不改 `_tavily_search()` / `_bocha_search()` 等已有实现
- ❌ 不改 Pipeline 编排逻辑（agent_engine 的核心流程）
- ❌ 不改 SSE 事件流（前端无感）
- ❌ 不改 DAG 拆解 prompt（LLM 看到的是工具名 + 描述，不改）
- ❌ 不引入 Skills/MCP 的运行时依赖（当前阶段只需 registry 抽象）
