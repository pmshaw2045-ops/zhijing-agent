"""
结构化日志配置 — JSON格式 + trace_id 注入（contextvars）

零依赖，纯Python logging。所有模块通过 get_logger() 获取已配置的logger。
trace_id 通过 contextvars 在线程/协程间自动传播，无需显式传参。
"""
import logging
import json
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

# contextvars — 每个请求独立的 trace_id，协程安全
_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")
_session_id_var: ContextVar[str] = ContextVar("session_id", default="-")


def set_request_context(trace_id: str, session_id: str = "") -> None:
    """设置当前请求的 trace_id 和 session_id（在请求开始时调用）"""
    _trace_id_var.set(trace_id)
    if session_id:
        _session_id_var.set(session_id)


def get_trace_id() -> str:
    """获取当前请求的 trace_id"""
    return _trace_id_var.get()


def get_session_id() -> str:
    """获取当前请求的 session_id"""
    return _session_id_var.get()


def setup_logging(level: str = "INFO") -> None:
    """初始化全局JSON格式日志"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JSONFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 抑制uvicorn的默认日志（它会重复输出）
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = True


def get_logger(name: str) -> logging.Logger:
    """获取已配置的logger"""
    return logging.getLogger(name)


class _JSONFormatter(logging.Formatter):
    """JSON格式日志，包含 timestamp/level/logger/trace_id/session_id/message"""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # 从 contextvars 注入 trace_id（如果未显式设置）
        trace_id = _trace_id_var.get()
        if trace_id != "-":
            entry["trace_id"] = trace_id
        session_id = _session_id_var.get()
        if session_id != "-":
            entry["sid"] = session_id
        if record.exc_info and record.exc_info[0]:
            entry["exc"] = str(record.exc_info[1])[:200]
        return json.dumps(entry, ensure_ascii=False)
