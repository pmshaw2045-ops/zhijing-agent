"""
ReportBuilder — 报告生成 + 模板路由

模板定义集中在 templates.py，ReportBuilder 只做路由和注入。
"""
from __future__ import annotations
import json
import re
import logging
from typing import Optional, List

from .llm_client import chat, MODEL_CHAT
from . import templates

logger = logging.getLogger(__name__)


class ReportBuilder:
    """报告生成器 — 按意图路由到独立策略，输出 JSON"""

    def __init__(self, memory=None):
        self.memory = memory

    # ── 路由 ──

    def build_prompt(self, intent: dict, mode: str = "selection",
                     exec_results: Optional[List[dict]] = None, session_id: str = "",
                     improvement_instructions: str = "",
                     template_id: str = None) -> str:
        """构建 prompt：解析模板 + 注入数据上下文"""
        goal = intent.get("goal", {})
        intent_type = intent.get("intent_type", "分析")
        data_context = self._build_data_context(exec_results)
        memory_note = self._build_memory_context(session_id, intent)

        # 从注册表解析模板
        tpl = templates.resolve_template(mode, template_id)
        prompt_builder = tpl["prompt_builder"]
        return prompt_builder(goal, intent_type, data_context, memory_note, improvement_instructions)

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

    # ── 生成 ──

    async def generate(self, intent: dict, mode: str = "selection",
                       exec_results: Optional[List[dict]] = None, session_id: str = "",
                       improvement_instructions: str = "", max_tokens: int = 3072,
                       prompt: Optional[str] = None,
                       template_id: str = None) -> str:
        if prompt is None:
            prompt = self.build_prompt(intent, mode, exec_results, session_id,
                                       improvement_instructions, template_id=template_id)
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
