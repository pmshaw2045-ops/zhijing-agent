"""
IntentRouter — 意图识别 + 路由

从 agent_engine 提取：Phase 1 意图识别全链路
依赖: llm_client (chat, extract_json), config (MODEL_FLASH), MemorySystem
"""
import json
import logging

from .llm_client import chat, extract_json
from .config import MODEL_FLASH
from .intent_registry import route_by_name, get_en_to_cn, get_mode_fallback, get_all_names, get_intent_signals

logger = logging.getLogger(__name__)

# 意图类型 → 模式路由（来自 registry）
_INTENT_ROUTE = {v: k for k, v in get_all_names().items()}
_EN_TO_CN = get_en_to_cn()
_MODE_FALLBACK = get_mode_fallback()


class IntentRouter:
    """意图识别 + 模式路由"""

    def __init__(self, memory=None):
        self.memory = memory

    # ── Prompt 构建 ──

    def build_prompt(self, user_input: str, mode: str, session_id: str = "") -> str:
        memory_context = self._build_memory_context(session_id)
        return f"""你是服饰电商意图识别专家。从用户输入提取结构化JSON。

{memory_context}
用户当前输入: "{user_input}"
模式提示: {mode}

意图判定规则:
- 文生图: 用户描述了一件衣服的款式/风格/面料/色彩等视觉特征，目的是生成图片。触发词含"生成""画一张""设计图""图片""摄影图""产品图""拍照""拍摄""照片""海报""模特图"等。纯视觉描述（如"XX风格+颜色+背景+摄影图"的组合）且无任何分析/对比/价格/选品词汇时，优先判定为文生图。
  注意：仅输入单一品类词（如仅"连衣裙""衬衫""泡泡袖"一个词）且无其他视觉维度（风格/颜色/材质/背景/摄影/设计图等）时，**不**判定为文生图。
- 单品选品分析: 用户要分析市场数据、价格带、趋势（含"选品""分析""机会""报告"等词）
- 商品文案生成: 用户要写标题/文案/详情页
- 多品牌竞品对标: 含两个及以上品牌对比
- 品类趋势洞察: 泛泛的趋势/流行方向询问
- 定价策略分析: 含定价/价格策略
- 上新排期优化: 含上新/排期/日历
- 无法识别（高优先级）: 输入与服饰电商**完全无关**（如"你好""天气""会计""数学题""GitHub""Python""股市""AI 竞争""微软"等任何非服饰零售领域），或信息完全不足以判断意图。**不要强行理解。与服饰/美妆/零售完全无关时，必须选择 无法识别。**

输出JSON含:
- intent_type: "单品选品分析"|"多品牌竞品对标"|"品类趋势洞察"|"商品文案生成"|"定价策略分析"|"上新排期优化"|"文生图"|"无法识别"
- confidence: 0-1
- entities: {{subject(品类/款式), category(类目), style(风格), time(时间), brands(品牌列表), platforms(平台列表)}}
- goal: {{任务类型, 分析对象, 品类, 风格, 时间范围, 目标平台, 竞品品牌, 核心关注点}}
- missing_info: [缺口] — 列举需要用户补充的信息
- context_note: "如从历史对话中有补充上下文，简述"

只输出JSON。"""

    # ── 核心分类 ──

    async def classify(self, user_input: str, mode: str = "selection",
                       session_id: str = "", prompt: str = None) -> dict:
        """LLM 意图分类 + 归一化"""
        if prompt is None:
            prompt = self.build_prompt(user_input, mode, session_id)
        raw = await chat(prompt, model=MODEL_FLASH, max_tokens=800)
        result = extract_json(raw)

        if not result or "intent_type" not in result:
            result = self._fallback(user_input, mode)

        result = self._normalize(result)
        return result

    # ── 路由 ──

    def route(self, intent: dict) -> str:
        """意图 → 执行模式"""
        it = intent.get("intent_type", "")
        for key, val in _INTENT_ROUTE.items():
            if key in it:
                return val
        return "selection"

    # ── 内部 ──

    def _normalize(self, intent: dict) -> dict:
        """英文→中文意图名映射"""
        it = intent.get("intent_type", "")
        if it in _EN_TO_CN:
            intent["intent_type"] = _EN_TO_CN[it]
        return intent

    def _fallback(self, text: str, mode: str) -> dict:
        """LLM 解析失败时的兜底"""
        return {
            "intent_type": _MODE_FALLBACK.get(mode, "单品选品分析"),
            "confidence": 0.5,
            "entities": {"subject": "", "category": "女装", "style": "", "time": "2026夏季",
                        "brands": [], "platforms": ["淘宝", "天猫"]},
            "goal": {"任务类型": _MODE_FALLBACK.get(mode), "分析对象": "女装",
                     "品类": "女装", "时间范围": "2026夏季"},
            "missing_info": ["需要更多上下文"],
            "_fallback": True
        }

    def _build_memory_context(self, session_id: str) -> str:
        """从 MemorySystem 构建MD格式的对话历史上下文"""
        if not self.memory:
            return ""
        try:
            ctx = self.memory.get_injectable_context(session_id)
            return ctx if ctx else ""
        except Exception as e:
            logger.warning(f"Memory context failed: {e}")
            return ""


def goal_to_text(goal: dict) -> str:
    """将结构化 goal dict 转为自然语言，节约 token 且更易读。过滤 null/空值/未指定。"""
    parts = []
    for key, label in [
        ("品类", None), ("分析对象", None), ("风格", None),
        ("时间范围", None), ("目标平台", "平台"), ("核心关注点", "关注"),
        ("价格带", None), ("面料", None),
    ]:
        val = goal.get(key, "")
        if val and str(val).strip() and str(val).strip() not in ("null", "未指定", "None"):
            v = str(val).strip()
            parts.append(f"{label or key}：{v}")
    brands = goal.get("竞品品牌", [])
    if brands and isinstance(brands, list) and len(brands) > 0:
        parts.append(f"品牌：{'、'.join(brands)}")
    return "，".join(parts) if parts else str(goal)[:200]
