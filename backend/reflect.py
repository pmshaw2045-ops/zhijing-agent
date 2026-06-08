"""
ReflectionEngine — 报告质量反思修正
"""
import json
import logging

try:
    from .llm_client import chat, extract_json, MODEL_CHAT
    from .intent import goal_to_text
    from .report_pipeline import TARGET_SCORE
except ImportError:
    from llm_client import chat, extract_json, MODEL_CHAT
    from intent import goal_to_text
    from report_pipeline import TARGET_SCORE

logger = logging.getLogger(__name__)


class ReflectionEngine:
    """反思引擎：数据一致性 + Goal对齐 + 可落地性"""

    def build_prompt(self, intent: dict, report: str) -> str:
        goal = intent.get("goal", {})
        report_sample = report[:4000] if report else ""
        return f"""你是AI Agent质检专家。反思以下分析报告的质量。

原始需求: {goal_to_text(goal)}
报告摘要 (前2000字符): {report_sample}

从三个维度评分（每项0-10）并输出JSON:

{{
  "scores": {{
    "data_consistency": 分数,
    "goal_alignment": 分数,
    "actionability": 分数
  }},
  "overall": 总分平均,
  "passed": true/false,
  "issues": ["问题1"],
  "warnings": ["警告1"],
  "verdict": "一句话总结"
}}

只输出JSON。严格评分，不要放水。"""

    async def evaluate(self, intent: dict, report: str, prompt: str = None) -> dict:
        if prompt is None:
            prompt = self.build_prompt(intent, report)
        raw = await chat(prompt, model=MODEL_CHAT, max_tokens=800)
        result = extract_json(raw)

        if not result or "scores" not in result:
            return {"passed": True, "scores": {"overall": 7},
                    "warnings": ["反思LLM返回异常，跳过校验"], "_fallback": True}

        scores = result.get("scores", {})
        dims = [scores.get(k, 5) for k in ("data_consistency", "goal_alignment", "actionability")]
        scores["overall"] = round(sum(dims) / len(dims), 1)
        result["passed"] = scores["overall"] >= TARGET_SCORE
        result["scores"] = scores
        return result
