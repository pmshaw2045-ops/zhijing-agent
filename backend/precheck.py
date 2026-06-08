"""
PrecheckEngine — 前置校验 + 澄清消息生成

基于 LLM 提取的 entities 判断信息完整性。intent 为空时用 user_input 兜底。
"""
import logging

try:
    from .intent_registry import INTENT_REGISTRY
except ImportError:
    from intent_registry import INTENT_REGISTRY

logger = logging.getLogger(__name__)


class PrecheckEngine:
    """前置校验引擎"""

    # 用户输入中出现了具体品类关键词 = 信息充分
    _PRODUCT_KW = ["裙", "衣", "裤", "衫", "装", "鞋", "包",
                   "连衣裙", "衬衫", "西装", "茶歇裙", "T恤", "风衣",
                   "半裙", "外套", "蕾丝", "雪纺", "棉麻", "苎麻"]

    def check(self, intent: dict, user_input: str = "") -> dict:
        goal = intent.get("goal", {}) if intent else {}
        entities = intent.get("entities", {}) if intent else {}
        intent_type = intent.get("intent_type", "") if intent else ""
        llm_missing = intent.get("missing_info", []) if intent else []

        hints = list(llm_missing)
        blocking_gaps = []

        # 快速降级：用户输入明显是文生图需求时，不触发通用校验
        _IMG_SIGNALS = ["摄影图", "产品图", "拍照", "拍摄", "照片", "海报", "模特图",
                        "生成一张", "画一张", "生成图片", "设计线稿", "设计图"]
        _looks_like_image = any(s in user_input for s in _IMG_SIGNALS)

        # 读取 registry 的 precheck 规则
        mode = self._find_mode(intent, intent_type)
        rules = INTENT_REGISTRY.get(mode, {}).get("precheck", [])
        # intent 数据缺失时的默认规则
        if not rules and not intent_type:
            rules = ["require_analysis_object"]

        # ── 品类/产品检查 ──
        if not _looks_like_image and intent_type != "文生图":
            if "require_analysis_object" in rules:
                cat = _extract(entities.get("category"))
                sub = _extract(entities.get("subject"))
                gcat = _extract(goal.get("品类"))
                has_specific = (
                    cat or gcat or
                    (sub and sub in user_input and len(sub) >= 2)
                )
                # 兜底：entity 分析失败时用 user_input 直接判断
                if not has_specific and _looks_like_product(user_input):
                    has_specific = True
                if not has_specific:
                    blocking_gaps.append(
                        "请明确要分析的具体品类或款式（如：法式茶歇裙、通勤西装裤）"
                    )

        # ── 品牌检查 ──
        if "require_brands" in rules:
            brands = goal.get("竞品品牌", []) or entities.get("brands", [])
            if _is_empty_list(brands):
                blocking_gaps.append("请指定要对标的品牌（至少1个）")

        # ── 文生图质量检查 ──
        if intent_type == "文生图" or _looks_like_image:
            if "image_quality" in rules:
                prompt_text = user_input
                if len(prompt_text) < 15:
                    blocking_gaps.append("图片描述太短了（至少15字），请补充款式细节、风格、背景等要素")
                _quality_kw = ["风格", "画质", "色彩", "光影", "构图", "氛围", "写实",
                              "插画", "摄影", "3D", "动漫", "背景", "白底", "纯色",
                              "模特", "上身", "穿着", "平铺", "挂拍", "线稿", "设计"]
                if not any(kw in prompt_text for kw in _quality_kw):
                    hints.append("可以补充：风格偏好、色彩光影、背景要求。默认为真实服装摄影图")

        return {
            "checks": {
                "info_completeness": {
                    "passed": len(blocking_gaps) == 0,
                    "gaps": blocking_gaps,
                    "hints": hints,
                }
            }
        }

    def build_clarify(self, check_result) -> str:
        """构建澄清消息。兼容 list 和 dict"""
        if isinstance(check_result, list):
            gaps, hints = check_result, []
        else:
            gaps = check_result.get("gaps", [])
            hints = check_result.get("hints", [])
        lines = ["📋 在开始分析之前，需要确认以下信息：\n"]
        for i, gap in enumerate(gaps, 1):
            lines.append(f"{i}. {gap}")
        if hints:
            lines.append(f"\n💡 {', '.join(hints[:3])}")
        lines.append("\n请补充以上信息，我会生成更精准的分析报告。")
        return "\n".join(lines)

    def _find_mode(self, intent: dict, intent_type: str) -> str:
        """根据 intent_type 查找 registry mode key"""
        mode = intent.get("_mode", "")
        if not mode and intent_type:
            for m, info in INTENT_REGISTRY.items():
                if info["name"] == intent_type:
                    return m
        return mode


def _looks_like_product(text: str) -> bool:
    """用户输入中是否包含具体品类关键词"""
    return any(kw in text for kw in PrecheckEngine._PRODUCT_KW)


def _extract(val):
    """提取有效字符串值，null/空/未指定/泛词返回 None"""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("null", "none", "未指定", "n/a",
                               "服装", "服饰", "女装", "男装", "童装",
                               "产品", "商品", "新品", "款式"):
        return None
    return s


def _is_empty_list(val) -> bool:
    if val is None:
        return True
    if isinstance(val, list):
        return len(val) == 0
    if isinstance(val, str):
        return val.strip() in ("", "null", "未指定", "[]")
    return False
