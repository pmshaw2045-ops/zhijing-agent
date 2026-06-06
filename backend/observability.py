"""
Observability — 结构化日志 + Token 追踪 + 请求指标

提供：
- RequestTracker: 请求级追踪（request_id, latency, status）
- TokenCounter: 模型级 token 累计
- MetricsCollector: 聚合指标
"""
import time
import logging
import threading
from collections import defaultdict

logger = logging.getLogger(__name__)


class TokenCounter:
    """线程安全的 token 用量计数器"""

    def __init__(self):
        self._lock = threading.Lock()
        self._tokens: dict[str, int] = defaultdict(int)  # model → total_tokens
        self._calls: dict[str, int] = defaultdict(int)    # model → call_count

    def record(self, model: str, tokens: int):
        with self._lock:
            self._tokens[model] += tokens
            self._calls[model] += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "by_model": dict(self._tokens),
                "calls_by_model": dict(self._calls),
                "total_tokens": sum(self._tokens.values()),
                "total_calls": sum(self._calls.values()),
            }


class RequestTracker:
    """请求级追踪器"""

    def __init__(self):
        self._lock = threading.Lock()
        self._total = 0
        self._success = 0
        self._errors = 0
        self._cancelled = 0
        self._latencies: list[float] = []  # 最近100条
        self._active = 0

    def start(self) -> str:
        """开始追踪，返回 request_id"""
        rid = f"req_{int(time.time()*1000)}_{id(self) % 10000}"
        with self._lock:
            self._total += 1
            self._active += 1
        return rid

    def finish(self, success: bool = True, cancelled: bool = False, latency_ms: float = 0):
        with self._lock:
            self._active = max(0, self._active - 1)
            if cancelled:
                self._cancelled += 1
            elif success:
                self._success += 1
            else:
                self._errors += 1
            if latency_ms > 0:
                self._latencies.append(latency_ms)
                if len(self._latencies) > 100:
                    self._latencies = self._latencies[-100:]

    def snapshot(self) -> dict:
        with self._lock:
            lats = sorted(self._latencies) if self._latencies else [0]
            n = len(lats)
            return {
                "total_requests": self._total,
                "active": self._active,
                "success": self._success,
                "errors": self._errors,
                "cancelled": self._cancelled,
                "latency_p50_ms": lats[n // 2] if n > 0 else 0,
                "latency_p95_ms": lats[int(n * 0.95)] if n > 1 else (lats[0] if n > 0 else 0),
                "latency_p99_ms": lats[int(n * 0.99)] if n > 2 else (lats[-1] if n > 0 else 0),
            }


# 全局单例
_token_counter = TokenCounter()
_request_tracker = RequestTracker()


def record_tokens(model: str, tokens: int):
    """记录一次 LLM token 消耗"""
    _token_counter.record(model, tokens)


def start_request() -> str:
    """开始一次请求追踪"""
    return _request_tracker.start()


def finish_request(success: bool = True, cancelled: bool = False, latency_ms: float = 0):
    """结束一次请求追踪"""
    _request_tracker.finish(success, cancelled, latency_ms)


def get_metrics() -> dict:
    """获取完整指标快照"""
    return {
        "requests": _request_tracker.snapshot(),
        "tokens": _token_counter.snapshot(),
        "timestamp": time.time(),
    }
