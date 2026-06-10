"""
测试 llm_client 重试机制: _is_retryable + _retry_async + _retry_sync
"""
import sys
import os
import asyncio
from unittest.mock import patch, MagicMock
from pathlib import Path

# sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")

import pytest
import httpx
from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
    APIStatusError,
)


# helpers
def _mock(spec):
    """创建能通过 isinstance(e, spec) 的 mock（仅 _is_retryable，不 raise）"""
    m = MagicMock()
    m.__class__ = spec
    return m


def _status_err(code):
    """创建带 status_code 的 APIStatusError 实例"""
    err = APIStatusError("err", response=MagicMock(), body=None)
    err.status_code = code
    return err


async def _noop_sleep(_s):
    pass


class TestIsRetryable:
    def _import(self):
        from backend.llm_client import _is_retryable
        return _is_retryable

    def test_retryable_openai_types(self):
        fn = self._import()
        assert fn(_mock(APIConnectionError)) is True
        assert fn(_mock(APITimeoutError)) is True
        assert fn(_mock(InternalServerError)) is True
        assert fn(_mock(RateLimitError)) is True

    def test_retryable_httpx_types(self):
        fn = self._import()
        assert fn(httpx.TimeoutException("")) is True
        assert fn(httpx.ConnectError("")) is True

    def test_retryable_asyncio_timeout(self):
        fn = self._import()
        assert fn(asyncio.TimeoutError()) is True

    def test_api_status_500_429(self):
        fn = self._import()
        assert fn(_status_err(500)) is True
        assert fn(_status_err(429)) is True

    def test_api_status_400_not_retryable(self):
        fn = self._import()
        assert fn(_status_err(400)) is False

    def test_generic_not_retryable(self):
        fn = self._import()
        assert fn(ValueError("generic")) is False


class TestRetryAsync:
    def _import(self):
        from backend.llm_client import _retry_async
        return _retry_async

    @pytest.mark.asyncio
    async def test_succeeds_first_attempt(self):
        _retry_async = self._import()
        async def ok():
            return "ok"
        result = await _retry_async(ok, "test-model")
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self):
        _retry_async = self._import()
        calls = [0]
        async def flaky():
            calls[0] += 1
            if calls[0] < 3:
                raise httpx.ConnectError("fail")
            return "recovered"
        with patch("backend.llm_client.asyncio.sleep", _noop_sleep):
            result = await _retry_async(flaky, "test-model")
        assert result == "recovered"
        assert calls[0] == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_non_retryable(self):
        _retry_async = self._import()
        calls = [0]
        async def bad():
            calls[0] += 1
            raise ValueError("bad")
        with patch("backend.llm_client.asyncio.sleep", _noop_sleep):
            with pytest.raises(ValueError):
                await _retry_async(bad, "test-model")
        assert calls[0] == 1

    @pytest.mark.asyncio
    async def test_fails_after_max_retries(self):
        _retry_async = self._import()
        calls = [0]
        async def always_timeout():
            calls[0] += 1
            raise asyncio.TimeoutError()
        with patch("backend.llm_client.asyncio.sleep", _noop_sleep):
            with pytest.raises(asyncio.TimeoutError):
                await _retry_async(always_timeout, "test-model")
        assert calls[0] == 3

    @pytest.mark.asyncio
    async def test_exponential_backoff(self):
        _retry_async = self._import()
        delays = []
        async def fail_twice():
            if len(delays) < 2:
                raise httpx.ConnectError("fail")
            return "ok"
        async def capture(s):
            delays.append(s)
        with patch("backend.llm_client.asyncio.sleep", capture):
            await _retry_async(fail_twice, "test-model")
        assert delays == [1.0, 2.0]


class TestRetrySync:
    def _import(self):
        from backend.llm_client import _retry_sync
        return _retry_sync

    def test_succeeds_first_attempt(self):
        _retry_sync = self._import()
        assert _retry_sync(lambda: "ok", "test-model") == "ok"

    def test_retries_then_succeeds(self):
        _retry_sync = self._import()
        calls = [0]
        def flaky():
            calls[0] += 1
            if calls[0] < 2:
                raise httpx.ConnectError("fail")
            return "recovered"
        with patch("backend.llm_client.time.sleep", return_value=None):
            result = _retry_sync(flaky, "test-model")
        assert result == "recovered"
        assert calls[0] == 2

    def test_no_retry_on_non_retryable(self):
        _retry_sync = self._import()
        calls = [0]
        def bad():
            calls[0] += 1
            raise ValueError("bad input")
        with pytest.raises(ValueError):
            _retry_sync(bad, "test-model")
        assert calls[0] == 1

    def test_fails_after_max_retries(self):
        _retry_sync = self._import()
        calls = [0]
        def always_timeout():
            calls[0] += 1
            raise httpx.TimeoutException("timeout")
        with patch("backend.llm_client.time.sleep", return_value=None):
            with pytest.raises(httpx.TimeoutException):
                _retry_sync(always_timeout, "test-model")
        assert calls[0] == 3
