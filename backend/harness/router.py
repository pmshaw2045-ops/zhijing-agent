"""CostRouter — 查询复杂度判定 + 执行深度控制"""
import logging

logger = logging.getLogger(__name__)

# Complexity 从 intent_registry 导入（避免循环依赖）
from ..intent_registry import Complexity, INTENT_REGISTRY

# 意图基础复杂度映射（从 registry 构建：中文名→复杂度）
_INTENT_COMPLEXITY = {info["name"]: info["complexity"] for info in INTENT_REGISTRY.values()}

# 追问关键词（降低复杂度）
_FOLLOWUP_KEYWORDS = ["深入", "详细", "继续", "再说说", "具体", "展开", "进一步"]

# 品牌数量阈值
_BRAND_THRESHOLD = 1  # >1个品牌 → 复杂度+1


class CostRouter:
    """查询复杂度路由器"""

    def classify(self, query: str, intent_type: str = "", 
                 brands: list = None, is_followup: bool = False) -> Complexity:
        """判定查询复杂度"""
        base = _INTENT_COMPLEXITY.get(intent_type, Complexity.MEDIUM)
        score = int(base)

        # 品牌数量（>1个品牌 → 复杂度+1）
        if brands and len(brands) > _BRAND_THRESHOLD:
            score += 1

        # 追问降低一级
        if is_followup or any(kw in query for kw in _FOLLOWUP_KEYWORDS):
            score -= 1

        # 钳位
        score = max(1, min(3, score))
        return Complexity(score)

    def should_include_reflection(self, complexity: Complexity) -> bool:
        """是否执行反思修正"""
        return complexity >= Complexity.MEDIUM

    def should_include_heavy_tools(self, complexity: Complexity) -> bool:
        """是否执行重量级工具（price_analyze, competitive_analyze, scoring_engine）"""
        return complexity >= Complexity.MEDIUM

    def get_max_retries(self, complexity: Complexity) -> int:
        """最大重试次数"""
        if complexity == Complexity.COMPLEX:
            return 2
        if complexity == Complexity.MEDIUM:
            return 1
        return 0

    def estimate_tokens(self, complexity: Complexity) -> int:
        """估算 token 消耗"""
        estimates = {
            Complexity.SIMPLE: 2000,
            Complexity.MEDIUM: 5000,
            Complexity.COMPLEX: 12000,
        }
        return estimates.get(complexity, 5000)

    def complexity_label(self, complexity: Complexity) -> str:
        return {Complexity.SIMPLE: "轻量", Complexity.MEDIUM: "标准", Complexity.COMPLEX: "完整"}.get(complexity, "未知")


# 全局单例
_router: CostRouter | None = None


def get_router() -> CostRouter:
    global _router
    if _router is None:
        _router = CostRouter()
    return _router
