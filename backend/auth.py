"""
API 认证 + 速率限制中间件

多 Key 支持：环境变量 API_KEYS 可配多个密钥（JSON格式或逗号分隔）。
每密钥独立限流。dev 模式零配置即可运行。
"""
import json
import os
import time
import hashlib
import logging
from collections import defaultdict
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_PUBLIC_PATHS = {"/", "/api/health", "/favicon.ico", "/style.css", "/render.js", "/console.js", "/sse.js", "/handler.js"}
_DEFAULT_TOKEN = "change-me-to-a-random-string"
_DEV_MODE = (
    ("API_TOKEN" not in os.environ and "API_KEYS" not in os.environ)
    or os.environ.get("API_TOKEN", "") == _DEFAULT_TOKEN
)
_RATE_LIMIT_RPM = int(os.environ.get("RATE_LIMIT_RPM", "60" if _DEV_MODE else "30"))


def _load_keys() -> dict[str, dict]:
    """加载 API 密钥。dev 模式生成随机 token，避免硬编码。"""
    raw = os.environ.get("API_KEYS", "")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {k.strip(): {"name": f"user_{i}", "rate_limit": _RATE_LIMIT_RPM}
                    for i, k in enumerate(raw.split(",")) if k.strip()}
    token = os.environ.get("API_TOKEN", "")
    if token:
        return {token: {"name": "default", "rate_limit": _RATE_LIMIT_RPM}}
    if _DEV_MODE:
        import secrets
        dev_token = secrets.token_urlsafe(16)
        logger.warning(f"🔑 DEV模式 — 自动生成API_TOKEN: {dev_token}")
        logger.warning(f"   设置环境变量: export API_TOKEN={dev_token}")
        return {dev_token: {"name": "dev_auto", "rate_limit": _RATE_LIMIT_RPM}}
    return {}


_api_keys = _load_keys()


class RateLimiter:
    """滑动窗口速率限制器，支持每 key 独立限流"""

    def __init__(self, default_rpm: int = 30):
        self.default_rpm = default_rpm
        self._window: dict[str, list[float]] = defaultdict(list)

    def check(self, client_id: str, rpm: int = None) -> bool:
        now = time.time()
        window = self._window[client_id]
        limit = rpm or self.default_rpm
        window[:] = [t for t in window if now - t < 60]
        if len(window) >= limit:
            return False
        window.append(now)
        if len(window) > limit + 10:
            window[:] = window[-limit:]
        return True


_rate_limiter = RateLimiter(_RATE_LIMIT_RPM)


class AuthMiddleware(BaseHTTPMiddleware):
    """多 Key Bearer Token 认证 + 速率限制"""

    async def dispatch(self, request: Request, call_next):
        if request.url.path in _PUBLIC_PATHS or request.url.path.startswith("/static"):
            return await call_next(request)
        if request.method == "OPTIONS":
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"

        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""

        if token and token in _api_keys:
            key_info = _api_keys[token]
            rpm = key_info.get("rate_limit", _RATE_LIMIT_RPM)
            if not _rate_limiter.check(token, rpm):
                return JSONResponse(status_code=429,
                    content={"error": f"Rate limit ({rpm}/min) exceeded for {key_info['name']}"})
            return await call_next(request)

        # Dev 模式：无 token 允许
        if _DEV_MODE and not auth:
            if not _rate_limiter.check(client_ip, _RATE_LIMIT_RPM):
                return JSONResponse(status_code=429,
                    content={"error": f"Rate limit exceeded ({_RATE_LIMIT_RPM}/min)"})
            response = await call_next(request)
            response.headers["X-Auth-Warning"] = "dev-mode"
            return response

        return JSONResponse(status_code=401, content={"error": "Invalid or missing API token"})


def get_auth_status() -> dict:
    """返回认证状态（用于 health check）"""
    return {
        "auth_enabled": not _DEV_MODE,
        "dev_mode": _DEV_MODE,
    }
