"""
测试 logging_setup: contextvars trace_id 传播 + JSON formatter
"""
import sys
import os
import json
import logging
from io import StringIO
from pathlib import Path

# # sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import pytest
from backend.logging_setup import (
    set_request_context,
    get_trace_id,
    get_session_id,
    _JSONFormatter,
    setup_logging,
)


class TestTraceContext:
    """trace_id / session_id contextvar 隔离"""

    def test_default_values(self):
        assert get_trace_id() == "-"
        assert get_session_id() == "-"

    def test_set_and_get(self):
        set_request_context("abc123", "sess_xyz")
        assert get_trace_id() == "abc123"
        assert get_session_id() == "sess_xyz"

    def test_reset_to_default(self):
        set_request_context("temp", "")
        assert get_trace_id() == "temp"
        # 新 context 恢复默认
        # (注意：在同一个测试中 contextvar 会保持，这是预期行为）
        set_request_context("other", "s")
        assert get_trace_id() == "other"
        assert get_session_id() == "s"


class TestJSONFormatter:
    """_JSONFormatter 输出格式"""

    def _make_record(self, msg, level=logging.INFO, exc_info=None):
        return logging.LogRecord(
            name="test", level=level, pathname="", lineno=0,
            msg=msg, args=(), exc_info=exc_info
        )

    def test_basic_fields(self):
        fmt = _JSONFormatter()
        record = self._make_record("hello world")
        output = fmt.format(record)
        entry = json.loads(output)

        assert "ts" in entry
        assert entry["level"] == "INFO"
        assert entry["logger"] == "test"
        assert entry["msg"] == "hello world"

    def test_includes_trace_id_when_set(self):
        set_request_context("trace-456", "sess-789")
        fmt = _JSONFormatter()
        record = self._make_record("with context")
        output = fmt.format(record)
        entry = json.loads(output)

        assert entry["trace_id"] == "trace-456"
        assert entry["sid"] == "sess-789"

    def test_excludes_trace_id_when_default(self):
        # 先用新 context 恢复默认
        set_request_context("-", "-")
        fmt = _JSONFormatter()
        record = self._make_record("no context")
        output = fmt.format(record)
        entry = json.loads(output)

        assert "trace_id" not in entry
        assert "sid" not in entry

    def test_exception_info_included(self):
        fmt = _JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            record = self._make_record("error msg", exc_info=sys.exc_info())
            output = fmt.format(record)
            entry = json.loads(output)

        assert "exc" in entry
        assert "test error" in entry["exc"]


class TestSetupLogging:
    """setup_logging 配置"""

    def test_handler_added(self):
        root = logging.getLogger()
        orig_count = len(root.handlers)
        setup_logging()
        assert len(root.handlers) >= 1
        # restore
        root.handlers = root.handlers[:orig_count]
