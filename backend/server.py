"""
FastAPI Server: 织镜 ZHÌJÌNG 后端服务
提供 SSE (Server-Sent Events) 流式接口
"""
import json
import asyncio
import time
import logging
import uuid
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, Response, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

try:
    from .agent_engine import AgentEngine
    from .memory import MemorySystem
    from .auth import AuthMiddleware, get_auth_status
    from .observability import start_request, finish_request, get_metrics
    from .logging_setup import setup_logging, set_request_context, get_trace_id
    from .config import MODEL_FLASH, MODEL_PRO
except ImportError:
    from agent_engine import AgentEngine
    from memory import MemorySystem
    from auth import AuthMiddleware, get_auth_status
    from observability import start_request, finish_request, get_metrics
    from logging_setup import setup_logging, set_request_context, get_trace_id
    from config import MODEL_FLASH, MODEL_PRO

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
logger = logging.getLogger("server")

# 全局实例
engine = AgentEngine()
memory_system = engine.memory

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .config import APP_ENV, IS_PROD
    setup_logging()
    logger.info(f"织镜 ZHÌJÌNG Agent 启动 (env={APP_ENV})")
    if IS_PROD:
        logger.info("  ⚠️  PRODUCTION 模式：认证已启用")
    logger.info("  API: http://localhost:8899/api/chat")
    logger.info("  前端: http://localhost:8899/")

    # === 启动自检（仅 dev 模式，prod 静默） ===
    if not IS_PROD:
        try:
            from .startup_diag import run_diagnostics, print_diagnostics
            diag_results = run_diagnostics()
            print_diagnostics(diag_results)
            has_issues = any(
                "error" in r or r.get("missing_params") or
                (r.get("pyc_mtime") is not None and not r.get("fresh", True))
                for r in diag_results
            )
            if has_issues:
                logger.warning("⚠️ 启动自检发现问题。建议: find backend -name __pycache__ -exec rm -rf {} +")
        except ImportError:
            logger.info("  startup_diag 模块不可用，跳过自检")
        except Exception as e:
            logger.warning(f"  启动自检异常: {e}")

    diag = engine.memory.stats()
    logger.info(f"  会话: {diag.get('total_sessions', '?')} | 知识: {diag.get('knowledge_count', '?')}")
    yield
    # 优雅关闭
    logger.info("正在关闭... 刷新记忆到磁盘")
    engine.memory._save()
    logger.info("记忆已持久化，服务关闭")

app = FastAPI(title="织镜 ZHÌJÌNG", version="2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(AuthMiddleware)


@app.get("/")
async def root():
    """前端页面"""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        html = index_path.read_text(encoding="utf-8")
        # 注入 API token（前端发请求时带上认证）
        api_token = os.environ.get("API_TOKEN", "")
        if api_token and api_token != "change-me-to-a-random-string":
            token_script = f"<script>const API_TOKEN='{api_token}';</script>"
            html = html.replace("<script>", f"{token_script}\n<script>", 1)
        return HTMLResponse(html,
                           headers={"Cache-Control": "no-cache"})


@app.get("/style.css")
async def style():
    return HTMLResponse((FRONTEND_DIR / "style.css").read_text(encoding="utf-8"),
                        media_type="text/css",
                        headers={"Cache-Control": "no-cache"})


@app.get("/console.js")
async def console_js():
    return HTMLResponse((FRONTEND_DIR / "console.js").read_text(encoding="utf-8"),
                        media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.get("/sse.js")
async def sse_js():
    return HTMLResponse((FRONTEND_DIR / "sse.js").read_text(encoding="utf-8"),
                        media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.get("/handler.js")
async def handler_js():
    return HTMLResponse((FRONTEND_DIR / "handler.js").read_text(encoding="utf-8"),
                        media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.get("/render.js")
async def render_js():
    return HTMLResponse((FRONTEND_DIR / "render.js").read_text(encoding="utf-8"),
                        media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.post("/api/chat")
async def chat(request: Request):
    """
    Agent对话接口 - SSE流式返回
    Request: { message, session_id?, mode? }
    Response: SSE Stream
    """
    body = await request.json()
    message = body.get("message", "").strip()
    session_id = body.get("session_id", str(uuid.uuid4())[:8])
    mode = body.get("mode", "selection")
    clarify_answer = body.get("clarify_answer", None)

    if not message:
        return JSONResponse({"error": "message is required"}, status_code=400)

    logger.info(f"📩 [{session_id}] {message[:60]}... (mode={mode})")
    request_start = time.time()
    start_request()
    set_request_context(f"req_{session_id}_{int(request_start*1000)%100000}", session_id)

    async def generate():
        cancelled = False
        try:
            async for event in engine.run_pipeline(message, session_id, mode, clarify_answer):
                if await request.is_disconnected():
                    logger.info(f"[{session_id}] 客户端已断开，取消Pipeline")
                    cancelled = True
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0)
        except Exception as e:
            logger.error(f"Pipeline error [{session_id}]: {type(e).__name__}: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': '服务内部错误，请重试'}, ensure_ascii=False)}\n\n"
        finally:
            finish_request(success=not cancelled, cancelled=cancelled,
                         latency_ms=(time.time()-request_start)*1000)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/api/health")
async def health():
    """健康检查"""
    return {
        "status": "ok",
        "engine": "ready",
        "models": {"flash": MODEL_FLASH, "pro": MODEL_PRO},
        "sessions": len(memory_system._store.get("sessions", {})),
        "auth": get_auth_status(),
    }


@app.get("/api/memory/{session_id}")
async def get_memory(session_id: str):
    """查询完整记忆状态"""
    stats = memory_system.stats(session_id)
    working = memory_system.get_working_memory(session_id)
    conv = memory_system.get_conversation(session_id)
    # 读取原始 store 中该 session 的完整数据
    session_data = memory_system._store.get("sessions", {}).get(session_id, {})
    return {
        "session_id": session_id,
        "stats": stats,
        "working_memory": working,
        "topic_context": session_data.get("topic_context", {}),
        "analysis_history": session_data.get("analysis_history", []),
        "long_term": memory_system._store.get("long_term", {}),
        "conversation": conv,
    }


@app.get("/api/memory/{session_id}/conversation")
async def get_conversation(session_id: str):
    """获取会话历史"""
    conv = memory_system.get_conversation(session_id)
    return {"session_id": session_id, "conversation": conv, "count": len(conv)}


@app.get("/api/metrics")
async def metrics():
    """系统指标（请求量/延迟/Token用量）"""
    return get_metrics()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8899, log_level="info")
