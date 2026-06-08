"""
ReportPipeline — 报告生成 + 反思修正辅助函数

从 agent_engine 提取的纯函数逻辑，降低 agent_engine 复杂度。
"""
import logging

logger = logging.getLogger(__name__)

TARGET_SCORE = 7


def build_improvement_instructions(reflection: dict, target: int = TARGET_SCORE) -> list[str]:
    """根据反思评分构建改进指令列表

    Args:
        reflection: 反思评分结果 {"scores": {"data_consistency": N, "goal_alignment": N, "actionability": N}}
        target: 目标分数阈值

    Returns:
        字符串列表，每个维度一个改进指令
    """
    scores = reflection.get("scores", {})
    dc = scores.get("data_consistency", 5)
    ga = scores.get("goal_alignment", 5)
    ac = scores.get("actionability", 5)

    fixes = []
    if dc < target:
        fixes.append(
            f"【数据一致性 {dc}/10→目标≥{target}】"
            "每个结论必须引用搜索数据原文片段作为证据。"
            "标注每条数据的来源(博查/Tavily)。"
            "统计数据用具体数字而非模糊描述。"
            "不确定的数据标注置信度(高/中/低)。"
        )
    if ga < target:
        fixes.append(
            f"【目标对齐 {ga}/10→目标≥{target}】"
            "逐条检查用户需求的每个要点是否被完整回答。"
            "遗漏的需求点必须补充。偏离主题的内容删除。"
        )
    if ac < target:
        fixes.append(
            f"【可落地性 {ac}/10→目标≥{target}】"
            "每个建议必须包含：具体¥价格/时间窗口/执行步骤/预期效果。"
            "'建议优化定价'不合格，'引流款定¥199、利润款定¥359、6月1日前上架'合格。"
        )
    return fixes


def build_improvement_prompt(scores: dict, fixes: list[str], target: int = TARGET_SCORE) -> str:
    """构建改进提示文本，注入到重试报告生成的 prompt 中

    Args:
        scores: 反思评分
        fixes: build_improvement_instructions 的输出
        target: 目标分数阈值

    Returns:
        用于注入报告生成 prompt 的改进提示
    """
    overall = scores.get("overall", 0)
    return f"⚠️ 质量不达标(当前{overall}/10，目标≥{target}/10)。必须逐条修复：\n" + "\n".join(fixes)
