"""
结构化日志配置 — JSON格式 + trace_id 注入

零依赖，纯Python logging。所有模块通过 get_logger() 获取已配置的logger。
"""
import logging
import json
import sys
from datetime import datetime, timezone


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
    """JSON格式日志，包含 timestamp/level/logger/trace_id/message"""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if hasattr(record, "trace_id"):
            entry["trace_id"] = record.trace_id
        if record.exc_info and record.exc_info[0]:
            entry["exc"] = str(record.exc_info[1])[:200]
        return json.dumps(entry, ensure_ascii=False)
