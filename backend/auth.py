"""
API 认证 + 速率限制中间件

Bearer Token 认证，默认 dev 模式（无 token 也行）。
生产环境设置 API_TOKEN 环境变量即可启用。
速率限制：RATE_LIMIT_RPM 环境变量控制（默认30次/分钟，dev模式60次/分钟）。
"""
import json
import os
import time
import logging
from collections import defaultdict
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# 公开路径：无需认证
_PUBLIC_PATHS = {"/", "/api/health", "/favicon.ico"}

# Token：环境变量 → config → dev默认值
_API_TOKEN = os.environ.get("API_TOKEN", "zhijing-dev-token-2026")
_DEV_MODE = "API_TOKEN" not in os.environ
_RATE_LIMIT_RPM = int(os.environ.get("RATE_LIMIT_RPM", "60" if _DEV_MODE else "30"))


class RateLimiter:
    """滑动窗口速率限制器"""

    def __init__(self, rpm: int = 30):
        self.rpm = rpm
        self._window: dict[str, list[float]] = defaultdict(list)

    def check(self, client_id: str) -> bool:
        """检查是否允许请求，返回 True=允许"""
        now = time.time()
        window = self._window[client_id]
        # 清理过期记录
        window[:] = [t for t in window if now - t < 60]
        if len(window) >= self.rpm:
            return False
        window.append(now)
        # 防止内存泄漏：每个 client 最多保留 rpm+10 条
        if len(window) > self.rpm + 10:
            window[:] = window[-self.rpm:]
        return True


_rate_limiter = RateLimiter(_RATE_LIMIT_RPM)


class AuthMiddleware(BaseHTTPMiddleware):
    """Bearer Token 认证 + 速率限制中间件"""

    async def dispatch(self, request: Request, call_next):
        # 公开路径跳过
        if request.url.path in _PUBLIC_PATHS or request.url.path.startswith("/static"):
            return await call_next(request)

        # OPTIONS 预检跳过
        if request.method == "OPTIONS":
            return await call_next(request)

        # 速率限制（基于客户端 IP）
        client_ip = request.client.host if request.client else "unknown"
        if not _rate_limiter.check(client_ip):
            return JSONResponse(
                status_code=429,
                content={"error": f"Rate limit exceeded ({_RATE_LIMIT_RPM} req/min)"}
            )

        # 检查 Authorization header
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            if token == _API_TOKEN:
                return await call_next(request)

        # Dev 模式：无 token 时允许但打 warning
        if _DEV_MODE and not auth:
            logger.warning(
                "DEV mode: no auth token. Set API_TOKEN env var for production."
            )
            response = await call_next(request)
            response.headers["X-Auth-Warning"] = "dev-mode-no-token"
            return response

        return JSONResponse(
            status_code=401,
            content={"error": "Invalid or missing API token"}
        )


def get_auth_status() -> dict:
    """返回认证状态（用于 health check）"""
    return {
        "auth_enabled": not _DEV_MODE,
        "dev_mode": _DEV_MODE,
    }
