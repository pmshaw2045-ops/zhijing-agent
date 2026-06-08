"""
ReportBuilder — 报告生成 + 模板管理

所有策略输出结构化 JSON，前端渲染引擎保证 100% 正确的 CSS 类名。
"""
from __future__ import annotations
import json
import re
import logging
from typing import Optional, List

try:
    from .llm_client import chat, chat_stream, MODEL_CHAT
except ImportError:
    from llm_client import chat, chat_stream, MODEL_CHAT

logger = logging.getLogger(__name__)


class ReportBuilder:
    """报告生成器 — 按意图路由到独立策略，输出 JSON"""

    def __init__(self, memory=None):
        self.memory = memory

    # ── 路由 ──

    def build_prompt(self, intent: dict, mode: str = "selection",
                     exec_results: Optional[List[dict]] = None, session_id: str = "",
                     improvement_instructions: str = "") -> str:
        goal = intent.get("goal", {})
        intent_type = intent.get("intent_type", "分析")
        data_context = self._build_data_context(exec_results)
        memory_note = self._build_memory_context(session_id, intent)

        strategy_map = {
            "selection": self._prompt_selection,
            "competitive": self._prompt_competitive,
            "trend": self._prompt_trend,
            "copy": self._prompt_copy,
            "pricing": self._prompt_pricing,
            "launch": self._prompt_launch,
        }
        strategy = strategy_map.get(mode, self._prompt_selection)
        return strategy(goal, intent_type, data_context, memory_note, improvement_instructions)

    def _build_data_context(self, exec_results: list) -> str:
        search_snippets = []
        tool_insights = []
        for r in (exec_results or []):
            tr = r.get("tool_result", {})
            if tr.get("tool") in ("web_search", "bocha_search"):
                source_label = "博查(中文)" if tr.get("source") == "bocha_chinese" else "Tavily"
                for s in tr.get("snippets", [])[:3]:
                    search_snippets.append(f"[{source_label}] {s[:200]}")
            elif tr.get("_llm_driven"):
                summary = tr.get("summary", "")
                if summary:
                    tool_insights.append(f"[{tr.get('tool','')}] {summary[:300]}")
                for td in tr.get("trend_directions", [])[:3]:
                    tool_insights.append(f"趋势: {td.get('direction','')} (热度{td.get('heat_score','?')})")
                for pb in tr.get("price_bands", [])[:3]:
                    tool_insights.append(f"价格带: {pb.get('label','')} ¥{pb.get('range_low','?')}-{pb.get('range_high','?')}")
                for comp in tr.get("competitors", [])[:3]:
                    tool_insights.append(f"竞品: {comp.get('brand','')} - {comp.get('positioning','')}")
        ctx = ""
        if search_snippets:
            ctx += "\n真实搜索数据:\n" + "\n".join(f"- {s}" for s in search_snippets[:5])
        if tool_insights:
            ctx += "\n\nLLM工具分析结果:\n" + "\n".join(f"- {s}" for s in tool_insights[:8])
        return ctx

    # ── 通用 JSON Schema ──
    _SCHEMA = """输出纯JSON（不要markdown代码块包裹）：
{
  "title": "报告标题",
  "sections": [
    {"type": "metrics", "data": {"items": [{"label":"指标名","value":"值","accent":"gold"}]}},
    {"type": "bar_chart", "data": {"items": [{"label":"标签","value":85,"color":"c1","suffix":"%"}]}},
    {"type": "table", "data": {"headers":["列1","列2"], "rows":[["数据","数据"]]}},
    {"type": "brand_card", "data": {"brand":"a","name":"名称","rows":[{"k":"标签","v":"值"}]}},
    {"type": "compare", "data": {"brands": [{"name":"品牌A","rows":[...]}, {"name":"品牌B","rows":[...]}]}},
    {"type": "swot", "data": {"brand":"a","name":"品牌名","s":["优势1"],"w":["劣势1"],"o":["机会1"],"t":["威胁1"]}},
    {"type": "insight", "data": {"style":"tip","title":"标题","body":"内容"}},
    {"type": "section_title", "data": {"text":"分区标题","style":"gold"}},
    {"type": "text", "data": {"content":"纯文本段落"}}
  ]
}

JSON规则：
- color值：c1(玫红), c2(金色), c3(绿色)
- accent值：gold/sage（可选，无则默认玫红）
- style(insight)：tip(绿色)/warn(橙色)/danger(红色)
- style(section_title)：gold/sage（可选）
- bar_chart的value是0-100的数字，suffix默认"%"
- 单品牌报告用brand_card，双品牌对比用compare
- 每个section严格按上面类型，不要自创类型名
- 只输出JSON，不输出任何说明文字"""

    # ── 各意图策略 ──

    def _prompt_selection(self, goal, intent_type, data, memory, extra):
        return f"""你是服饰电商选品分析师。基于搜索数据生成选品分析JSON报告。

任务: {intent_type}
需求: {json.dumps(goal, ensure_ascii=False, indent=2)[:600]}
{memory}{data}{extra}

报告结构（按顺序填入 sections 数组）：
1. 数据总览 — metrics（3-4个指标：搜索热度/竞争强度/利润空间/趋势匹配度）
2. 趋势方向 — section_title + insight.tip ×2-3条
3. 价格带分析 — section_title + bar_chart（3-5个价格带，c1/c2/c3三色）
4. 竞品格局 — section_title + table（品牌|定位|价格带|优势|劣势）
5. TOP选品方向 — section_title + brand_card ×2-3个
6. 避坑建议 — insight.warn

{self._SCHEMA}"""

    def _prompt_competitive(self, goal, intent_type, data, memory, extra):
        return f"""你是服饰电商竞品分析师。基于搜索数据生成竞品对标JSON报告。

任务: {intent_type}
需求: {json.dumps(goal, ensure_ascii=False, indent=2)[:600]}
{memory}{data}{extra}

报告结构（按顺序）：
1. 品牌概览 — compare（定位/价格带/风格/渠道）
2. 核心指标对比 — section_title + metrics（均价/SKU数/店铺评分/搜索热度，用accent区分品牌）
3. 价格带对比 — section_title + bar_chart（每个品牌每个价格带一行，c1=品牌A, c2=品牌B。如："太平鸟 ¥0-199"值15色c1, "伊芙丽 ¥0-199"值8色c2）
4. 面料策略对比 — section_title + table（维度|品牌A|品牌B）
5. 设计风格对比 — section_title + table
6. SWOT矩阵 — swot ×2（brand_a和brand_b各一个）
7. 差异化机会 — insight.tip

{self._SCHEMA}"""

    def _prompt_trend(self, goal, intent_type, data, memory, extra):
        return f"""你是服饰电商趋势分析师。生成趋势洞察JSON报告。

任务: {intent_type}
需求: {json.dumps(goal, ensure_ascii=False, indent=2)[:600]}
{memory}{data}{extra}

报告结构：
1. 趋势热度排行 — section_title + bar_chart（3-5个方向，c1/c2/c3）
2. 面料趋势 — section_title + table（面料|热度|适用品类）
3. 廓形趋势 — section_title + table（廓形|热度|代表品牌）
4. 色彩趋势 — section_title + metrics（3-4个色系）+ table
5. 选品建议 — section_title + brand_card ×2-3个

{self._SCHEMA}"""

    def _prompt_copy(self, goal, intent_type, data, memory, extra):
        return f"""你是资深电商文案策划。直接生成商品文案JSON报告，不做任何市场分析。

任务: {intent_type}
商品信息: {json.dumps(goal, ensure_ascii=False, indent=2)[:400]}
{data}

报告结构：
1. 核心关键词 — metrics（3-4个搜索热度关键词）
2. 淘宝标题 — section_title + insight.tip ×2-3个（标注字符数）
3. 详情页卖点 — section_title + table（卖点维度|文案内容）
4. 抖音口播 — section_title + text（完整口播文案）
5. 小红书种草 — section_title + text（正文+话题标签）

{self._SCHEMA}"""

    def _prompt_pricing(self, goal, intent_type, data, memory, extra):
        return f"""你是服饰电商定价策略师。生成定价策略JSON报告。

任务: {intent_type}
需求: {json.dumps(goal, ensure_ascii=False, indent=2)[:400]}
{memory}{data}{extra}

报告结构：
1. 价格带分布 — section_title + bar_chart（3-5个区间，c1/c2/c3）
2. 竞品定价对比 — section_title + table（品牌|引流款|利润款|形象款）
3. 成本利润测算 — section_title + metrics（3-4项成本）
4. 定价建议 — section_title + brand_card ×3（引流款/利润款/形象款）
5. 促销节奏 — insight.tip

{self._SCHEMA}"""

    def _prompt_launch(self, goal, intent_type, data, memory, extra):
        return f"""你是服饰电商运营专家。生成上新排期JSON报告。

任务: {intent_type}
需求: {json.dumps(goal, ensure_ascii=False, indent=2)[:400]}
{memory}{data}{extra}

报告结构：
1. 品类季节曲线 — section_title + bar_chart（1-12月热度，c1淡季/c2旺季）
2. 大促日历 — section_title + table（节点|日期|折扣建议|备货提前期）
3. 最佳上新窗口 — section_title + metrics（3个窗口）
4. 测款节奏 — insight.tip
5. 风险日历 — insight.danger

{self._SCHEMA}"""

    # ── 生成 ──

    async def generate(self, intent: dict, mode: str = "selection",
                       exec_results: Optional[List[dict]] = None, session_id: str = "",
                       improvement_instructions: str = "", max_tokens: int = 3072,
                       prompt: Optional[str] = None) -> str:
        if prompt is None:
            prompt = self.build_prompt(intent, mode, exec_results, session_id, improvement_instructions)
        raw = await chat(prompt, model=MODEL_CHAT, max_tokens=max_tokens)
        return _clean(raw)

    def _build_memory_context(self, session_id: str, intent: dict) -> str:
        """生成Markdown格式的记忆上下文，注入LLM prompt"""
        if not self.memory:
            return ""
        try:
            ctx = self.memory.get_injectable_context(session_id)
            return f"\n\n---\n## 🧠 Agent记忆上下文\n{ctx}" if ctx else ""
        except Exception as e:
            logger.warning(f"Memory context for report failed: {e}")
            return ""


def _clean(text: str) -> str:
    """清理LLM输出 — 提取JSON"""
    text = text.strip()

    # 移除 markdown 代码块
    if '```json' in text:
        start = text.find('```json')
        end = text.rfind('```')
        if start != -1 and end != -1 and end > start:
            text = text[start+7:end].strip()
    elif text.startswith('```'):
        lines = text.split('\n')
        text = '\n'.join(lines[1:-1] if lines and lines[-1].strip() == '```' else lines[1:])
    text = text.replace('```json', '').replace('```', '').strip()

    # 只保留JSON内容（从 { 到最后一个 }）
    lt = text.find('{')
    rt = text.rfind('}')
    if lt >= 0 and rt > lt:
        text = text[lt:rt+1]
    # 二次清理：去掉尾随文本
    if text.endswith('}'):
        pass  # already clean
    else:
        # 找最后一个完整的 } 
        last = text.rfind('}')
        if last > 0:
            text = text[:last+1]

    return text.strip()
