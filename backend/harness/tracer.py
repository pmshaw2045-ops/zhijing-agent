"""TraceCollector — 全链路追踪，支持评估和调试"""
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class TraceCollector:
    """轻量级全链路追踪收集器"""

    def __init__(self):
        self._traces: dict[str, dict] = {}  # trace_id → trace_data

    def start(self, session_id: str, query: str) -> str:
        """开始一次追踪，返回trace_id"""
        trace_id = f"trace_{int(time.time()*1000)}_{session_id}"
        self._traces[trace_id] = {
            "trace_id": trace_id,
            "session_id": session_id,
            "query": query[:200],
            "start_time": time.time(),
            "steps": [],
            "total_llm_calls": 0,
            "total_tool_calls": 0,
            "total_tokens": 0,
            "status": "running",
        }
        return trace_id

    def record(self, trace_id: str, phase: str, data: dict = None,
               latency_ms: float = 0, tokens: int = 0, model: str = ""):
        """记录一个步骤"""
        trace = self._traces.get(trace_id)
        if not trace:
            return

        trace["steps"].append({
            "phase": phase,
            "data": data,
            "latency_ms": round(latency_ms, 1),
            "tokens": tokens,
            "model": model,
        })
        trace["total_tokens"] += tokens
        if model:
            trace["total_llm_calls"] += 1
        if phase == "execute":
            trace["total_tool_calls"] += 1

    def finish(self, trace_id: str, success: bool = True) -> Optional[dict]:
        """结束追踪，返回摘要"""
        trace = self._traces.get(trace_id)
        if not trace:
            return None

        trace["status"] = "success" if success else "failed"
        trace["total_latency_ms"] = round((time.time() - trace["start_time"]) * 1000)
        trace["end_time"] = time.time()

        summary = {
            "trace_id": trace_id,
            "session_id": trace["session_id"],
            "query": trace["query"],
            "latency_ms": trace["total_latency_ms"],
            "llm_calls": trace["total_llm_calls"],
            "tool_calls": trace["total_tool_calls"],
            "total_tokens": trace["total_tokens"],
            "status": trace["status"],
            "phase_count": len(trace["steps"]),
        }
        logger.info(f"Trace {trace_id}: {summary}")
        return summary

    def get_trace(self, trace_id: str) -> Optional[dict]:
        return self._traces.get(trace_id)

    def list_recent(self, limit: int = 10) -> list[dict]:
        traces = sorted(self._traces.values(), key=lambda t: t.get("start_time", 0), reverse=True)
        return traces[:limit]

    def cleanup(self, max_traces: int = 100):
        """清理过期trace，防止内存泄漏"""
        if len(self._traces) > max_traces:
            old_keys = sorted(self._traces.keys())[:len(self._traces) - max_traces]
            for k in old_keys:
                del self._traces[k]


# 全局单例
_collector: TraceCollector | None = None


def get_tracer() -> TraceCollector:
    global _collector
    if _collector is None:
        _collector = TraceCollector()
    return _collector
