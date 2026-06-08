"""
DecomposeEngine — DAG任务拆解

LLM自主设计DAG + 回退保护 + 多格式兼容标准化
"""
from __future__ import annotations
import json
import logging

try:
    from .llm_client import chat, extract_json, MODEL_PRO
    from .intent_registry import INTENT_REGISTRY, get_all_names, get_decompose_rule
    from .tools import AVAILABLE_TOOLS
except ImportError:
    from llm_client import chat, extract_json, MODEL_PRO
    from intent_registry import INTENT_REGISTRY, get_all_names, get_decompose_rule
    from tools import AVAILABLE_TOOLS

logger = logging.getLogger(__name__)


class DecomposeEngine:
    """DAG拆解引擎：LLM自主设计 + 标准化 + 回退保护"""

    def __init__(self, dag_loader):
        self.dag_loader = dag_loader

    def build_prompt(self, intent: dict, detected_mode: str) -> str:
        goal = intent.get("goal", {})
        intent_type = intent.get("intent_type", "分析")
        # 从 registry 读取该意图的相关工具（而非全量 AVAILABLE_TOOLS）
        relevant = INTENT_REGISTRY.get(detected_mode, {}).get("relevant_tools", [])
        if not relevant:
            relevant = [t["name"] for t in AVAILABLE_TOOLS]
        tools_list = ", ".join(relevant)
        prompt = f"""仅输出JSON对象，不要引言、不要解释、不要markdown代码块。

    你是任务规划专家。根据用户意图和可用工具，自主设计最优DAG任务流。

    意图类型: {intent_type}
    用户目标: {_goal_to_text(goal)}

    可用工具: {tools_list}

    工具选择规则:
    - bocha_search: 中文搜索首选，覆盖淘宝/天猫/京东商品页、中文新闻、百科。服饰电商场景默认用bocha_search
    - web_search: 英文搜索(Tavily)，仅用于需要Google/国际数据时
    - 其他工具按需选择

    规则:
    - 不同意图类型需要不同任务结构（不要所有场景都用相同DAG）
"""
        # 从 registry 动态生成各意图的拆解规则
        for mode, name in get_all_names().items():
            rule = get_decompose_rule(mode)
            prompt += f"- {name}: {rule}\n"
        prompt += """- 服饰电商中文场景，搜索任务默认使用bocha_search

    输出JSON（只输出JSON，不要任何说明文字）:
    {{"tasks":[{{"id":"T1","desc":"任务描述(必填)","tool":"工具名","deps":[],"parallel_group":0}}],
     "rationale":"为什么这样设计DAG"}}

    ⚠️ 每个任务的desc字段必填一句话。永远不要省略。
    自主设计规则:
    - 仅使用上面列出的可用工具，不要编造工具名
    - 无依赖关系的任务放在同一parallel_group实现并行
    - 3-6个任务，服饰中文场景默认用bocha_search
    - 根据意图类型决定需要哪些分析工具，不需要的不要加"""
        return prompt

    async def decompose(self, intent: dict, detected_mode: str, prompt: str = None) -> dict:
        if prompt is None:
            prompt = self.build_prompt(intent, detected_mode)
        template = self.dag_loader.load(detected_mode) or self.dag_loader.load("selection")
        raw = await chat(prompt, model=MODEL_PRO, max_tokens=2000, json_mode=True)
        result = extract_json(raw)

        # 标准化 task 字段名（json_mode 保证输出是 JSON，只需统一字段名）
        if result and "tasks" in result:
            normalized = []
            for t in result["tasks"]:
                normalized.append({
                    "id": str(t.get("id", "")),
                    "desc": t.get("desc", t.get("description",
                            t.get("params", {}).get("query", ""))),
                    "tool": t.get("tool", "web_search"),
                    "deps": t.get("deps", t.get("depends_on", t.get("dependencies", []))),
                    "parallel_group": t.get("parallel_group", t.get("group", 0)),
                })
            result["tasks"] = normalized

        if not result or "tasks" not in result:
            # fallback: LLM 返回不含 tasks → 用模板兜底
            logger.warning(f"[{detected_mode}] LLM decompose 失败，回退模板。"
                          f" 原始返回前200字: {raw[:200]}")
            return {
                "tasks": template["tasks"],
                "parallel_groups": [["T2", "T3", "T4"]],
                "_fallback": True,
            }

        # LLM 自主生成的 DAG
        result["_llm_generated"] = True
        return result


def _goal_to_text(goal: dict) -> str:
    """将结构化 goal dict 转为自然语言，节约 token 且更易读"""
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

    