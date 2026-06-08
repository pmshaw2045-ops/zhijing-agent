# SSE 断线重连 — 技术设计文档

## 问题

当前前端使用 `fetch() + response.body.getReader()` 消费 SSE 流。如果连接在 Pipeline 运行中断开（网络波动、服务器重启等），用户会看到「错误」提示且无恢复机制，需要手动重发请求。

## 设计方案

### 总体策略：自动重连 + 幂等请求

```
用户发消息 → fetch SSE
  ├── 正常完成 → 显示结果
  └── 连接断开 → 自动重连（最多 N 次）
                  ├── 后端仍在跑 → 等执行完成（session_id 追踪）
                  └── 后端没跑过 → 重新执行
```

### 前端改动

#### 1. 重试逻辑（`sendMessage` + `sendMessageWithClarify`）

```javascript
async function sendMessage(text, mode) {
  const MAX_RETRIES = 3;
  const RETRY_DELAY = 2000; // 2秒
  
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      await doStreamFetch(text, mode, sessionId);
      break; // 成功则退出重试循环
    } catch (err) {
      if (attempt >= MAX_RETRIES) throw err; // 最后一次失败→抛给上层
      if (isCancelledError(err)) throw err; // 用户主动取消→不重试
      
      updateStatus('连接中断，' + (MAX_RETRIES - attempt) + '秒后重试...');
      await sleep(RETRY_DELAY * (attempt + 1)); // 指数退避
    }
  }
}
```

#### 2. 提取公共 SSE 读取函数

将 `sendMessage` 和 `sendMessageWithClarify` 中重复的流读取逻辑提取为 `_readSSEStream(response, reportBubble, signal)`。

```javascript
async function _readSSEStream(response, reportBubble, signal) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  
  while (true) {
    if (signal && signal.aborted) throw new CancelledError();
    
    const { done, value } = await reader.read();
    if (done) break;
    
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || ''; // 保留未完成行
    // ... 处理完整行
  }
}
```

#### 3. 添加 AbortController 支持

允许用户取消正在进行的请求（通过「停止」按钮或新消息中断旧请求）。

### 后端改动

#### 1. Session 级 Pipeline 锁

当前设计：每个请求独立启动 `run_pipeline`，无 session 追踪。

```python
# memory.py 新增
self._active_pipelines: dict[str, asyncio.Event] = {}

async def wait_or_start_pipeline(self, session_id: str) -> bool:
    """返回 True 表示是新启动，False 表示等待已有 pipeline"""
    if session_id in self._active_pipelines:
        await self._active_pipelines[session_id].wait()
        return False
    self._active_pipelines[session_id] = asyncio.Event()
    return True

def finish_pipeline(self, session_id: str):
    if session_id in self._active_pipelines:
        self._active_pipelines[session_id].set()
        del self._active_pipelines[session_id]
```

#### 2. 可恢复的 SSE 流

将 `run_pipeline` 的事件序列改为可重入的：
- 如果 session 已有缓存结果 → 直接返回（已实现）
- 如果 session 正在运行 → 等待结果而非重新执行
- 如果 session 无记录 → 新建 pipeline

### 边界条件

| 场景 | 行为 |
|------|------|
| 网络闪断后恢复 | 自动重连 + 指数退避（2s/4s/8s） |
| 用户主动重发 | 取消旧请求，新建 pipeline |
| 服务重启 | 重连失败 → 显示「服务不可用」 |
| 长 Pipeline 超时 | 前端超时后重连，后端如果还在跑则返回已有结果 |
| 多次重连均失败 | 最多 3 次，之后显示失败提示 |
| 会话已过期 | 后端返回 404 → 前端提示重新输入 |

### 不建议的方案

1. **WebSocket** — 当前 SSE 方案工作正常，WebSocket 需要完全重写前后端通信层，引入不必要的复杂度
2. **EventSource API** — 只支持 GET 请求，而我们的接口是 POST，需要额外改造
3. **Service Worker** — 过度设计，对当前问题域来说太重

### 实施计划

| 步骤 | 内容 | 文件 | 预估 |
|------|------|------|------|
| 1 | 提取公共 `_readSSEStream` 函数 | `frontend/index.html` | 30min |
| 2 | 添加重试循环 + 指数退避 | `frontend/index.html` | 20min |
| 3 | 添加 AbortController / 取消机制 | `frontend/index.html` | 20min |
| 4 | 后端 session 级 pipeline 锁 | `backend/memory.py` | 20min |
| 5 | 后端可重入 pipeline 保护 | `backend/agent_engine.py` | 30min |
| 6 | 测试：pytest + 手动 curl 模拟断连 | `tests/` | 20min |

### 回滚方案

每步独立可回滚。步骤 4+5 后端改动最小（新增 Event，不修改现有逻辑），步骤 1-3 前端改动可通过 `git checkout -- frontend/index.html` 回滚。
