"""
织镜 Fashion Agent — 统一配置模块

优先级: os.environ > 项目 .env.{APP_ENV} > .env > ~/.hermes/.env

环境切换: APP_ENV=dev|staging|prod
- dev:     .env.dev → .env (本地开发)
- staging: .env.staging (预发布)
- prod:    .env.prod 或纯环境变量 (生产)
"""
import os
import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

# ============================================================
# 项目根目录
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ============================================================
# 当前环境
# ============================================================
APP_ENV = os.environ.get("APP_ENV", "dev").lower()
IS_DEV = APP_ENV == "dev"
IS_STAGING = APP_ENV == "staging"
IS_PROD = APP_ENV == "prod"

# ============================================================
# .env 加载 (python-dotenv) — 分层优先级
# ============================================================
try:
    from dotenv import load_dotenv
    
    # 1. 基础 .env（所有环境共享）
    _base_env = PROJECT_ROOT / ".env"
    if _base_env.exists():
        load_dotenv(_base_env)
        logger.info("Loaded .env (base)")
    
    # 2. 环境专属 .env.{APP_ENV}（覆盖基础值）
    _env_specific = PROJECT_ROOT / f".env.{APP_ENV}"
    if _env_specific.exists():
        load_dotenv(_env_specific, override=True)
        logger.info(f"Loaded .env.{APP_ENV} (override)")
except ImportError:
    logger.debug("python-dotenv not installed, skipping .env auto-load")


def get_key(name: str, hermes_fallback: bool = True) -> str:
    """
    统一密钥读取:
    1. os.environ (云部署/容器注入)
    2. 项目 .env (python-dotenv 已 load)
    3. ~/.hermes/.env 解析 (本地开发兜底)
    """
    val = os.environ.get(name, "")
    if val:
        return val

    if hermes_fallback:
        hermes_env = Path.home() / ".hermes" / ".env"
        if hermes_env.exists():
            try:
                with open(hermes_env) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith(f"{name}=") and not line.startswith("#"):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if val and val != "***":
                                return val
            except Exception:
                pass

    return ""


# ============================================================
# LLM 密钥
# ============================================================
DEEPSEEK_API_KEY = get_key("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# 模型常量
MODEL_FLASH = "deepseek-chat"    # V3 快速模型，用于意图识别
MODEL_PRO = "deepseek-v4-pro"    # V4 Pro 推理模型，DAG 拆解/反思
MODEL_CHAT = "deepseek-chat"     # V3 标准模型，报告/工具提取

# ============================================================
# 豆包 Seedream 文生图
# ============================================================
ARK_API_KEY = get_key("ARK_API_KEY")
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
ARK_MODEL = "doubao-seedream-5-0-260128"

# ============================================================
# 搜索工具密钥
# ============================================================
TAVILY_API_KEY = get_key("TAVILY_API_KEY")
TAVILY_URL = "https://api.tavily.com/search"

BOCHA_API_KEY = get_key("BOCHA_API_KEY")
BOCHA_URL = "https://api.bochaai.com/v1/web-search"

# ============================================================
# 启动诊断
# ============================================================
def diagnostics() -> Dict[str, object]:
    """返回密钥配置状态 (不含密钥值)"""
    return {
        "env": APP_ENV,
        "is_prod": IS_PROD,
        "deepseek": bool(DEEPSEEK_API_KEY),
        "ark_image": bool(ARK_API_KEY),
        "tavily": bool(TAVILY_API_KEY),
        "bocha": bool(BOCHA_API_KEY),
        "env_source": (
            "os.environ" if os.environ.get("DEEPSEEK_API_KEY") else
            "project .env" if (PROJECT_ROOT / ".env").exists() else
            "~/.hermes/.env" if (Path.home() / ".hermes" / ".env").exists() else
            "none"
        )
    }


if __name__ == "__main__":
    diag = diagnostics()
    print("织镜配置诊断:")
    for k, v in diag.items():
        print(f"  {k}: {'✅' if v else '❌'} {v if not isinstance(v, bool) else ''}")
