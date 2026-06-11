"""
FastAPI Server: 织镜 ZHÌJÌNG 后端服务
提供 SSE (Server-Sent Events) 流式接口
"""
import json
import asyncio
import time
import logging
import uuid
import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, Response, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .agent_engine import AgentEngine
from .memory import MemorySystem
from .auth import AuthMiddleware, get_auth_status
from .observability import start_request, finish_request, get_metrics
from .logging_setup import setup_logging, set_request_context, get_trace_id
from .config import MODEL_FLASH, MODEL_PRO

# 评测引擎（延迟导入，避免环路）
import sys as _sys
_eval_imported = False
async def _get_eval_engine():
    global _eval_imported
    if not _eval_imported:
        _scripts_dir = str(Path(__file__).parent.parent / "scripts")
        if _scripts_dir not in _sys.path:
            _sys.path.insert(0, _scripts_dir)
        _eval_imported = True
    import eval as _eval_mod
    return _eval_mod

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
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})


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
    template_id = body.get("template", None)

    if not message:
        return JSONResponse({"error": "message is required"}, status_code=400)

    logger.info(f"📩 [{session_id}] {message[:60]}... (mode={mode})")
    request_start = time.time()
    start_request()
    set_request_context(f"req_{session_id}_{int(request_start*1000)%100000}", session_id)

    async def generate():
        cancelled = False
        try:
            async for event in engine.run_pipeline(message, session_id, mode, clarify_answer, template_id=template_id):
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


# ══════════════════════════════════════════════════
#   Eval 评测接口（后台任务 + 进度轮询）
# ══════════════════════════════════════════════════

_eval_task = None          # 当前 running 的协程
_eval_progress = {"running": False, "completed": 0, "total": 0, "current": "",
                  "phase": "idle", "start_time": 0}
_eval_result_lock = asyncio.Lock()


@app.get("/api/templates")
async def list_templates():
    """返回所有可用报告模板"""
    from . import templates as _tpl_mod
    return {"templates": _tpl_mod.list_all_templates(), "count": len(_tpl_mod.list_all_templates())}


@app.get("/eval")
async def eval_page():
    """评测可视化页面"""
    eval_path = FRONTEND_DIR / "eval.html"
    if eval_path.exists():
        return HTMLResponse(
            eval_path.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-cache"}
        )
    return HTMLResponse("<h2>eval.html not found</h2>", status_code=404)


@app.post("/api/eval/run")
async def run_eval(request: Request):
    """启动后台评测任务（立即返回）"""
    global _eval_task
    body = await request.json()
    tags = body.get("tags")
    case_id = body.get("case_id")
    skip_judge = body.get("skip_judge", False)
    parallel = body.get("parallel", 3)

    if _eval_progress.get("running"):
        return JSONResponse({
            "status": "already_running",
            "progress": _eval_progress,
        })

    logger.info(f"🧪 评测启动（后台）: tags={tags}, case_id={case_id}")

    # 更新进度状态
    _eval_progress["running"] = True
    _eval_progress["completed"] = 0
    _eval_progress["total"] = 0
    _eval_progress["current"] = ""
    _eval_progress["phase"] = "loading"
    _eval_progress["start_time"] = time.time()

    # 清空旧缓存
    try:
        eval_mod = await _get_eval_engine()
        eval_mod.clear_cache()
        # 清空磁盘缓存
        _cache_path = Path(__file__).parent.parent / "data" / "eval_cache.json"
        if _cache_path.exists():
            _cache_path.unlink()
    except Exception:
        pass

    async def _run_eval_bg():
        global _eval_progress
        try:
            eval_mod = await _get_eval_engine()

            def _on_progress(completed, total, current_id):
                _eval_progress["completed"] = completed
                _eval_progress["total"] = total
                _eval_progress["current"] = current_id or ""
                _eval_progress["phase"] = "running"

            result = await eval_mod.run_eval(
                tags=tags,
                case_id=case_id,
                skip_llm_judge=skip_judge,
                parallel=parallel,
                progress_callback=_on_progress,
            )
            _eval_progress["phase"] = "complete"
            _eval_progress["running"] = False
            logger.info(f"🧪 评测完成: {result['summary'].get('pass_rate', 0)}%")
        except Exception as e:
            logger.error(f"🧪 评测失败: {e}", exc_info=True)
            _eval_progress["phase"] = "error"
            _eval_progress["running"] = False
            _eval_progress["error"] = str(e)[:200]

    _eval_task = asyncio.create_task(_run_eval_bg())

    return {"status": "started", "message": "评测已启动，轮询 /api/eval/status 获取进度"}


@app.get("/api/eval/status")
async def eval_status():
    """获取评测状态/进度/最新结果"""
    progress = dict(_eval_progress)

    # 加载缓存结果（如有）
    try:
        eval_mod = await _get_eval_engine()
        cache = eval_mod.get_cached_results()
        has_cache = cache["summary"] is not None
        return {
            "status": "ok",
            "progress": progress,
            "has_data": has_cache,
            "summary": cache["summary"],
            "cases": cache.get("cases", []),
            "case_count": len(cache.get("cases", [])),
        }
    except Exception as e:
        return {
            "status": "ok",
            "progress": progress,
            "has_data": False,
            "error": str(e)[:100],
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8899, log_level="info")
