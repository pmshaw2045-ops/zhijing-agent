"""
LLM Client v7: 直连 DeepSeek API + 模型分级 + 统一配置
- deepseek-chat:   轻量任务 (意图识别, 工具提取)
- deepseek-v4-pro: 重量任务 (DAG拆解, 反思)

密钥从 config.py 统一读取 (os.environ > 项目.env > ~/.hermes/.env)
"""
import json
import re
import logging
import httpx
from openai import AsyncOpenAI, OpenAI

try:
    from .config import (
        DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL,
        ARK_API_KEY, ARK_BASE_URL, ARK_MODEL,
        MODEL_FLASH, MODEL_PRO, MODEL_CHAT,
    )
    from .observability import record_tokens
except ImportError:
    from config import (
        DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL,
        ARK_API_KEY, ARK_BASE_URL, ARK_MODEL,
        MODEL_FLASH, MODEL_PRO, MODEL_CHAT,
    )
    from observability import record_tokens

logger = logging.getLogger(__name__)

# ====== 客户端初始化 ======
_async_client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
_sync_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

_img_client = None
if ARK_API_KEY:
    try:
        _img_client = OpenAI(api_key=ARK_API_KEY, base_url=ARK_BASE_URL)
    except Exception as e:
        logger.warning(f"ARK image client init failed: {e}")
else:
    logger.warning("ARK_API_KEY not found! Image generation will fail.")


async def chat(prompt: str, model: str = MODEL_FLASH, max_tokens: int = 1024) -> str:
    """异步调用 DeepSeek Chat API"""
    try:
        resp = await _async_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.7,
        )
        output = resp.choices[0].message.content.strip()
        # 估算 token 用量：中文≈1.5字符/token，粗略用字符数/2
        est_tokens = len(prompt) // 2 + len(output) // 2
        record_tokens(model, est_tokens)
        return output
    except Exception as e:
        logger.error(f"DeepSeek API error (async, model={model}): {e}")
        raise


def chat_sync(prompt: str, model: str = MODEL_FLASH, max_tokens: int = 1024, timeout: int = 30) -> str:
    """同步调用 DeepSeek Chat API — 供工具层使用"""
    try:
        resp = _sync_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.3,
        )
        output = resp.choices[0].message.content.strip()
        est_tokens = len(prompt) // 2 + len(output) // 2
        record_tokens(model, est_tokens)
        return output
    except Exception as e:
        logger.error(f"DeepSeek API error (sync, model={model}): {e}")
        raise


def extract_json(text: str) -> dict:
    """从LLM输出提取JSON"""
    text = text.strip()
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = re.sub(r'```\s*$', '', text)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r'\{[\s\S]*\}', text)
    if m:
        try:
            return json.loads(m.group())
        except:
            pass
    return {}


def generate_image(prompt: str, size: str = "2K") -> dict:
    """调用豆包 Seedream 文生图"""
    if not _img_client:
        return {"error": "ARK_API_KEY not configured", "url": None}

    try:
        resp = _img_client.images.generate(
            model=ARK_MODEL,
            prompt=prompt,
            size=size,
            response_format="url",
            extra_body={"watermark": True},
        )
        url = resp.data[0].url if resp.data else None
        return {"url": url, "model": ARK_MODEL, "size": size, "prompt": prompt}
    except Exception as e:
        logger.error(f"Image generation failed: {e}")
        return {"error": str(e), "url": None}
