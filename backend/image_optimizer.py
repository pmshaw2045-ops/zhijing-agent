"""
ImageOptimizer — LLM 驱动文生图 prompt 优化
"""
import logging

try:
    from .llm_client import chat, MODEL_FLASH
except ImportError:
    from llm_client import chat, MODEL_FLASH

logger = logging.getLogger(__name__)


class ImageOptimizer:
    """文生图 prompt 优化器：智能识别风格（摄影/线稿/模特）并改写"""

    def build_prompt(self, user_prompt: str) -> str:
        is_design = any(kw in user_prompt for kw in
                        ["设计图", "设计稿", "线稿", "效果图", "款式图", "版型图", "草图", "手绘"])
        wants_model = any(kw in user_prompt for kw in
                          ["模特", "上身", "穿着", "真人", "试穿", "走秀"])

        if is_design:
            style_guide = "这是一张服装设计师专业线稿/效果图，手绘风格或电脑绘图，展示服装的正面和背面版型，标注面料和设计细节"
        elif wants_model:
            style_guide = "这是一张真实时尚摄影照片，真人模特穿着展示，专业影棚灯光，高清商业摄影质感"
        else:
            style_guide = "这是一张真实服装产品摄影图，衣服挂在衣架上或平铺展示，纯色干净背景，高清商业摄影质感，电商白底图风格，展示服装全貌"

        return f"""你是服装摄影/设计prompt优化专家。将用户的描述改写为适合AI生图的prompt。

风格要求: {style_guide}

规则:
1. 开头必须明确这是一张什么类型的图片（真实摄影/设计稿/平铺图）
2. 如果是真实摄影，强调「高清摄影」「商业摄影」「真实质感」「写实」，避免插画/卡通/3D渲染等词汇
3. 面料质感作为辅助描述，不要变成面料特写
4. 描述整件衣服的全貌，展示服装整体廓形
5. 保留用户指定的风格、色彩、光影要求
6. 豆包Seedream偏好：主体明确、光影真实、质感细腻

用户描述: {user_prompt}

只输出优化后的prompt文本，不要加任何解释。"""

    async def optimize(self, user_prompt: str, prompt: str = None) -> str:
        if prompt is None:
            prompt = self.build_prompt(user_prompt)
        try:
            raw = await chat(prompt, model=MODEL_FLASH, max_tokens=400)
            return raw.strip() or user_prompt
        except Exception:
            return user_prompt
