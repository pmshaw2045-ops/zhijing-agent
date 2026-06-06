"""
PrecheckEngine — 前置校验 + 澄清消息生成

从 agent_engine 提取：Phase 2 前置校验逻辑
"""
import logging

logger = logging.getLogger(__name__)


class PrecheckEngine:
    """前置校验引擎：检查信息完整性，必要时触发澄清交互"""

    def check(self, intent: dict, user_input: str = "") -> dict:
        """校验意图中的信息完整性"""
        goal = intent.get("goal", {})
        llm_missing = intent.get("missing_info", [])
        hints = list(llm_missing)
        blocking_gaps = []

        # 快速降级：用户输入明显是文生图需求时，不触发通用校验
        _IMG_SIGNALS = ["摄影图", "产品图", "拍照", "拍摄", "照片", "海报", "模特图",
                        "生成一张", "画一张", "生成图片", "设计线稿", "设计图"]
        _looks_like_image = any(s in user_input for s in _IMG_SIGNALS)

        # 检查分析对象（文生图跳过）
        if not _looks_like_image and intent.get("intent_type") != "文生图":
            analysis_object = goal.get("分析对象", "")
            if not analysis_object or analysis_object in ("", "品类", "女装", "产品", "未指定"):
                blocking_gaps.append("请明确要分析的具体品类或款式（如：法式茶歇裙、通勤西装裤）")

        # 竞品对标：必须有品牌
        if intent.get("intent_type") == "多品牌竞品对标":
            brands = goal.get("竞品品牌", [])
            if not brands or not isinstance(brands, list) or len(brands) == 0:
                if isinstance(brands, str) and brands not in ("", "未指定"):
                    pass  # 单个品牌名也接受
                else:
                    blocking_gaps.append("请指定要对标的品牌（至少1个）")

        # 文生图：检查描述质量（无论LLM意图判定为何，只要输入像图片需求就检查）
        if intent.get("intent_type") == "文生图" or _looks_like_image:
            prompt_text = user_input  # 直接用原始输入，不依赖LLM提取的"核心关注点"
            if len(prompt_text) < 15:
                blocking_gaps.append("图片描述太短了（至少15字），请补充款式细节、风格、背景等要素")
            # 检查是否缺乏关键质量词
            _quality_kw = ["风格", "画质", "色彩", "光影", "构图", "氛围", "写实", "插画", "摄影", "3D", "动漫",
                          "背景", "白底", "纯色", "模特", "上身", "穿着", "平铺", "挂拍", "线稿", "设计"]
            if not any(kw in prompt_text for kw in _quality_kw):
                hints.append("可以补充：风格偏好、色彩光影、背景要求、画质（2K/4K）。默认生成为真实服装摄影图")

        return {
            "checks": {
                "info_completeness": {
                    "passed": len(blocking_gaps) == 0,
                    "gaps": blocking_gaps,
                    "hints": hints,
                },
                "permission": {"passed": True, "gaps": []},
                "compliance": {"passed": True, "gaps": []},
                "dependency": {"passed": True, "gaps": []},
            },
            "confidence_matrix": {
                "依赖置信度": 0.90 if len(blocking_gaps) == 0 else 0.70,
                "可执行性": 0.92,
                "综合判定": "直接自动执行" if len(blocking_gaps) == 0 else "需用户补充信息",
            },
        }

    def build_clarify(self, gaps: list) -> str:
        """生成澄清消息"""
        lines = ["📋 在开始分析之前，需要确认以下信息：", ""]
        for i, gap in enumerate(gaps, 1):
            lines.append(f"{i}. {gap}")
        lines.append("")
        lines.append("请补充以上信息，我会生成更精准的分析报告。")
        return "\n".join(lines)
