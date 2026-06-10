"""Tools v5: 配置化搜索 + LLM驱动分析
- web_search: Web搜索 (路由: tavily/bocha, 可配置)
- bocha_search: Web搜索 (路由: tavily/bocha, 可配置)
- trend_analyze: LLM从搜索结果提取趋势洞察
- price_analyze: LLM从搜索结果提取价格带数据
- competitive_analyze: LLM从搜索结果分析竞品格局
- scoring_engine: LLM多维度综合评分
- report_generate: 标记 → 由agent_engine的LLM报告接管
"""
import json
import logging
import httpx

from .llm_client import chat_sync, extract_json, MODEL_FLASH, generate_image
from .config import TAVILY_API_KEY, TAVILY_URL, BOCHA_API_KEY, BOCHA_URL, SEARCH_PROVIDER

logger = logging.getLogger(__name__)

# 统一密钥变量（兼容旧引用）
TAVILY_KEY = TAVILY_API_KEY
BOCHA_KEY = BOCHA_API_KEY

AVAILABLE_TOOLS = [
    {"name": "web_search",        "description": "Web搜索(英文/全球)", "parameters": {"query": "搜索关键词"}},
    {"name": "bocha_search",      "description": "Web搜索(中文/电商)", "parameters": {"query": "搜索关键词"}},
    {"name": "trend_analyze",     "description": "LLM从搜索结果提取趋势洞察", "parameters": {"query": "分析指令", "raw_data": "原始搜索结果"}},
    {"name": "price_analyze",     "description": "LLM从搜索结果提取价格带数据", "parameters": {"query": "分析指令", "raw_data": "原始搜索结果"}},
    {"name": "competitive_analyze","description": "LLM从搜索结果分析竞品格局", "parameters": {"query": "分析指令", "raw_data": "原始搜索结果"}},
    {"name": "scoring_engine",    "description": "LLM多维度综合评分", "parameters": {"candidates": "候选列表", "criteria": "评分维度"}},
    {"name": "report_generate",   "description": "交由LLM生成最终报告", "parameters": {"report_type": "报告类型", "data": "汇总数据"}},
    {"name": "image_generate",    "description": "豆包Seedream文生图", "parameters": {"prompt": "图片描述(越详细越好,含风格/构图/色彩/画质)", "size": "分辨率(2K/4K)"}},
]


# ====== Tavily Search (unchanged) ======

async def execute_tool(name: str, params: dict) -> dict:
    """异步工具执行"""
    if name == "web_search":
        return await _search(params.get("query", ""), params.get("limit", 5), "web_search")
    elif name == "bocha_search":
        return await _search(params.get("query", ""), params.get("limit", 8), "bocha_search")
    elif name in ("trend_analyze", "price_analyze", "competitive_analyze", "scoring_engine"):
        return execute_tool_sync(name, params)
    elif name == "report_generate":
        return {"status": "delegated_to_llm", "summary": "报告由LLM根据以上数据综合生成"}
    elif name == "image_generate":
        return _image_generate(params)
    return {"error": f"Unknown tool: {name}"}


async def _tavily_search(query: str, limit: int = 5) -> dict:
    """真实 Tavily API 搜索"""
    if not TAVILY_KEY:
        return {"tool": "web_search", "query": query, "error": "Tavily key未配置", "snippets": [], "summary": f"搜索'{query}'（无API key）"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(TAVILY_URL, json={
                "api_key": TAVILY_KEY, "query": query, "search_depth": "basic",
                "max_results": min(limit, 5), "include_answer": True,
            })
            data = resp.json()
        results = data.get("results", [])
        answer = data.get("answer", "")
        snippets = [f"[{r.get('title','')}]({r.get('url','')}): {r.get('content','')[:200]}" for r in results[:limit]]
        summary = answer if answer else "; ".join([r.get("content", "")[:100] for r in results[:3]])
        return {
            "tool": "web_search", "query": query, "results_count": len(results),
            "summary": summary[:500] if summary else f"搜索'{query}'返回{len(results)}条结果",
            "snippets": snippets[:3], "raw_results": results[:limit],
        }
    except Exception as e:
        logger.error(f"Tavily search failed: {e}")
        return {"tool": "web_search", "query": query, "error": str(e), "summary": "搜索出错", "snippets": []}


# ====== 博查搜索 (Bocha AI) ======

async def _bocha_search(query: str, limit: int = 8) -> dict:
    """博查AI中文搜索 — 覆盖国内电商/新闻/百科内容"""
    if not BOCHA_KEY:
        return {"tool": "bocha_search", "query": query, "error": "博查API key未配置", "snippets": [], "summary": f"搜索'{query}'（无API key）"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(BOCHA_URL, json={
                "query": query,
                "freshness": "oneYear",
                "summary": True,
                "count": min(limit, 10),
            }, headers={
                "Authorization": f"Bearer {BOCHA_KEY}",
                "Content-Type": "application/json",
            })
            data = resp.json()
            body = data.get("data", data)  # 博查返回 {"code":200, "data":{...}}

        web_pages = body.get("webPages", {}).get("value", [])
        snippets = []
        for page in web_pages[:limit]:
            title = page.get("name", "")
            url = page.get("url", "")
            snippet = page.get("snippet", "")
            summary = page.get("summary", "")
            text = summary if summary else snippet
            snippets.append(f"[{title}]({url}): {text[:200]}")

        # 用第一条结果的summary作为整体摘要
        first_summary = web_pages[0].get("summary", "") if web_pages else ""
        summary = first_summary[:500] if first_summary else f"博查搜索'{query}'返回{len(web_pages)}条结果"

        return {
            "tool": "bocha_search",
            "query": query,
            "results_count": len(web_pages),
            "summary": summary,
            "snippets": snippets[:5],
            "raw_results": web_pages[:limit],
            "source": "bocha_chinese",
        }
    except Exception as e:
        logger.error(f"Bocha search failed: {e}")
        return {"tool": "bocha_search", "query": query, "error": str(e), "summary": "博查搜索出错", "snippets": [], "source": "bocha_chinese"}


# ====== 搜索路由层（配置化 Provider 路由） ======

async def _search(query: str, limit: int, tool_name: str) -> dict:
    """统一搜索路由：根据配置选择搜索引擎"""
    provider = SEARCH_PROVIDER
    # auto: 根据工具名 + 可用key自动选择
    if provider == "auto":
        if tool_name == "web_search":
            provider = "tavily" if TAVILY_KEY else "bocha" if BOCHA_KEY else "none"
        else:
            provider = "bocha" if BOCHA_KEY else "tavily" if TAVILY_KEY else "none"

    if provider == "tavily":
        return await _tavily_search(query, limit)
    elif provider == "bocha":
        return await _bocha_search(query, limit)
    else:
        return {"tool": tool_name, "query": query, "error": "未配置搜索API",
                "snippets": [], "summary": f"搜索'{query}'（无可用搜索API）"}


def _search_sync(query: str, limit: int, tool_name: str) -> dict:
    """同步搜索路由"""
    provider = SEARCH_PROVIDER
    if provider == "auto":
        if tool_name == "web_search":
            provider = "tavily" if TAVILY_KEY else "bocha" if BOCHA_KEY else "none"
        else:
            provider = "bocha" if BOCHA_KEY else "tavily" if TAVILY_KEY else "none"

    if provider == "tavily":
        return _tavily_search_sync(query, limit)
    elif provider == "bocha":
        return _bocha_search_sync(query, limit)
    else:
        return {"tool": tool_name, "query": query, "error": "未配置搜索API",
                "snippets": [], "summary": f"搜索'{query}'（无可用搜索API）"}


# ====== LLM-Driven Analysis Tools ======

def _llm_extract(prompt_template: str, raw_data: dict, query: str,
                 output_desc: str, max_tokens: int = 800) -> dict:
    """通用LLM提取：构建prompt → 调用LLM → 解析JSON → 返回结构化结果"""
    # 提取搜索文本素材
    search_text = _build_search_context(raw_data, query)

    prompt = prompt_template.format(query=query, search_text=search_text)

    try:
        raw = chat_sync(prompt, model=MODEL_FLASH, max_tokens=max_tokens)
        result = extract_json(raw)
        if result:
            result["data_source"] = "search_engine" if search_text else "llm_knowledge"
            result["_llm_driven"] = True
            result["_llm_prompt"] = prompt  # 用于控制台展示
            return result
    except Exception as e:
        logger.warning(f"LLM extraction failed for {output_desc}: {e}")

    # Fallback: 返回框架数据，标注为非LLM
    return {
        "tool": output_desc, "error": "LLM extraction failed",
        "data_source": "fallback", "_llm_driven": False,
        "summary": f"{output_desc}：LLM调用失败，报告生成阶段将基于搜索原始数据直接分析"
    }


def _build_search_context(raw_data: dict, query: str) -> str:
    """从上游搜索结果构建文本上下文"""
    if not raw_data or not isinstance(raw_data, dict):
        return ""
    # 优先取 snippets
    snippets = raw_data.get("snippets", [])
    if not snippets and "raw_results" in raw_data:
        snippets = [r.get("content", "")[:200] for r in raw_data.get("raw_results", [])]
    if snippets:
        return "\n".join(f"- {s}" for s in snippets[:5])
    # 其次取 summary
    summary = raw_data.get("summary", "")
    if summary:
        return summary[:1500]
    return query


def _extract_trends(params: dict) -> dict:
    """LLM从搜索结果提取趋势洞察"""
    prompt = """你是服饰电商趋势分析师。从以下搜索结果中提取趋势洞察。

搜索主题: {query}

搜索结果:
{search_text}

输出JSON（只输出JSON，不要markdown包裹）:
{{
  "trend_directions": [
    {{"direction": "趋势方向名", "heat_score": 0-100, "evidence": "来自搜索的关键证据", "keywords": ["关键词1"]}}
  ],
  "fabric_trends": ["面料趋势1"],
  "style_trends": ["风格趋势1"],
  "silhouette_trends": ["廓形趋势1"],
  "summary": "一句话总结核心趋势"
}}

如果搜索结果不包含相关信息，基于你的服饰电商知识给出合理推断，但标注 confidence 为 low。"""

    result = _llm_extract(prompt, params.get("raw_data", {}), params.get("query", ""), "trend_analyze")
    result["tool"] = "trend_analyze"
    return result


def _extract_pricing(params: dict) -> dict:
    """LLM从搜索结果提取价格带数据"""
    prompt = """你是服饰电商定价分析师。从以下搜索结果中提取价格信息。如果是竞品对比场景，需分别提取各品牌数据。

搜索主题: {query}

搜索结果:
{search_text}

输出JSON（只输出JSON，必须包含所有字段）:
{{
  "price_bands": [
    {{"label": "价格带名称", "range_low": 最低价(¥数字), "range_high": 最高价(¥数字), "description": "该价格带特征", "competition_level": "高/中/低"}}
  ],
  "brand_pricing": [
    {{"brand": "品牌名", "avg_price": 均价(¥数字), "low": 最低价, "high": 最高价, "core_range": "主力区间描述"}}
  ],
  "market_price_range": "品类主力价格带区间",
  "profit_analysis": "基于行业毛利率的利润空间分析（具体到百分比区间）",
  "pricing_suggestions": ["具体定价建议1", "建议2"],
  "summary": "一句话总结价格格局"
}}

价格单位使用人民币¥。如果搜索结果有具体价格数字，优先使用；如果无，基于行业知识合理估算并标注。"""

    result = _llm_extract(prompt, params.get("raw_data", {}), params.get("query", ""), "price_analyze", max_tokens=1000)
    result["tool"] = "price_analyze"
    return result


def _extract_competitive(params: dict) -> dict:
    """LLM从搜索结果分析竞品格局"""
    prompt = """你是服饰电商竞品分析师。从以下搜索结果中提取品牌A vs 品牌B的竞品对比。

搜索主题: {query}

搜索结果:
{search_text}

⚠️ 你必须输出完整的对比分析。即使搜索结果信息有限，也要基于你对中国服饰电商品牌的行业知识，给出具体、可落地的分析。

输出JSON（只输出JSON，必须包含所有字段，不允许留空）:
{{
  "brand_a": {{
    "name": "品牌A名称",
    "positioning": "品牌定位（如：中高端都市通勤、快时尚等）",
    "price_range": "连衣裙主力价格带（¥数字区间）",
    "target_age": "目标年龄段",
    "style_keywords": ["风格关键词"],
    "fabric_focus": "面料策略（如：以聚酯纤维为主、真丝+羊毛高端线等）",
    "channel_strength": "渠道优势（天猫/线下/抖音等）",
    "estimated_gmv": "连衣裙类目年GMV估算（如：5-10亿）"
  }},
  "brand_b": {{
    "name": "品牌B名称",
    "positioning": "...同上结构",
    "price_range": "...",
    "target_age": "...",
    "style_keywords": [],
    "fabric_focus": "...",
    "channel_strength": "...",
    "estimated_gmv": "..."
  }},
  "comparison": {{
    "price_gap": "价差分析（谁更高、高多少、原因）",
    "style_differentiation": "设计风格差异（具体到廓形/颜色/细节）",
    "fabric_advantage": "面料策略优劣势对比",
    "target_user_overlap": "用户群重叠度（高/中/低+理由）",
    "channel_contrast": "渠道布局差异"
  }},
  "swot_brand_a": {{"strengths":[], "weaknesses":[], "opportunities":[], "threats":[]}},
  "swot_brand_b": {{"strengths":[], "weaknesses":[], "opportunities":[], "threats":[]}},
  "differentiation_opportunities": ["如果你是第三方品牌，可切入的差异化机会"],
  "summary": "200字以内总结核心竞争格局"
}}

品牌名默认为搜索主题中提及的前两个中文品牌。如果只有一个品牌，第二个填写"未指定"。"""

    result = _llm_extract(prompt, params.get("raw_data", {}), params.get("query", ""), "competitive_analyze", max_tokens=1200)
    result["tool"] = "competitive_analyze"
    return result


def _score_candidates(params: dict) -> dict:
    """LLM多维度综合评分"""
    candidates = params.get("candidates", [])
    criteria = params.get("criteria", [])
    if isinstance(candidates, str):
        candidates = [candidates]

    # 简单场景不用LLM
    if not candidates:
        return {"tool": "scoring_engine", "scored": 0, "summary": "无候选需要评分", "_llm_driven": False}

    prompt = f"""你是选品评估专家。对以下候选进行多维度评分。

候选: {json.dumps(candidates, ensure_ascii=False)}
维度: {json.dumps(criteria, ensure_ascii=False) if criteria else '["市场热度","利润空间","竞争强度","趋势匹配度","可落地性"]'}

输出JSON:
{{"scores":[{{"candidate":"候选名","total":总分1-100,"dimensions":{{"维度名":分数}}}}],"summary":"综合评估"}}"""

    # 直接调用 LLM，不走 _llm_extract（后者会对 prompt 二次 .format()，与 f-string 中的 {} 冲突）
    try:
        raw = chat_sync(prompt, model=MODEL_FLASH, max_tokens=600)
        result = extract_json(raw)
        if result:
            result["data_source"] = "llm_knowledge"
            result["_llm_driven"] = True
            result["_llm_prompt"] = prompt
            result["tool"] = "scoring_engine"
            result["scored"] = len(candidates)
            return result
    except Exception as e:
        logger.warning(f"scoring_engine LLM调用失败: {e}")

    return {"tool": "scoring_engine", "error": "LLM调用失败", "scored": 0,
            "data_source": "fallback", "_llm_driven": False,
            "summary": "评分工具LLM调用失败，报告生成阶段将基于数据直接分析"}


# ====== Sync Wrapper ======

def execute_tool_sync(name: str, params: dict) -> dict:
    """同步工具执行 — agent_engine使用"""
    if name == "web_search":
        return _search_sync(params.get("query", ""), params.get("limit", 5), "web_search")
    elif name == "bocha_search":
        return _search_sync(params.get("query", ""), params.get("limit", 8), "bocha_search")
    elif name == "trend_analyze":
        return _extract_trends(params)
    elif name == "price_analyze":
        return _extract_pricing(params)
    elif name == "competitive_analyze":
        return _extract_competitive(params)
    elif name == "scoring_engine":
        return _score_candidates(params)
    elif name == "report_generate":
        return {"status": "delegated_to_llm", "summary": "报告由LLM综合生成"}
    elif name == "image_generate":
        return _image_generate(params)
    return {"error": f"Unknown: {name}"}


def _tavily_search_sync(query: str, limit: int = 5) -> dict:
    """同步 Tavily 搜索"""
    if not TAVILY_KEY:
        return {"tool": "web_search", "query": query, "error": "No API key", "snippets": [], "summary": "Tavily key未配置"}
    try:
        resp = httpx.post(TAVILY_URL, json={
            "api_key": TAVILY_KEY, "query": query, "search_depth": "basic",
            "max_results": min(limit, 5), "include_answer": True,
        }, timeout=15)
        data = resp.json()
        results = data.get("results", [])
        answer = data.get("answer", "")
        summary = answer if answer else "; ".join([r.get("content", "")[:100] for r in results[:3]])
        return {
            "tool": "web_search", "query": query, "results_count": len(results),
            "summary": summary[:500], "snippets": [r.get("content", "")[:200] for r in results[:3]],
            "raw_results": results[:limit],
        }
    except Exception as e:
        logger.error(f"web_search failed: {e}")
        return {"tool": "web_search", "query": query, "error": str(e), "summary": "搜索出错", "snippets": []}


def _bocha_search_sync(query: str, limit: int = 8) -> dict:
    """同步博查AI中文搜索"""
    if not BOCHA_KEY:
        return {"tool": "bocha_search", "query": query, "error": "No API key", "snippets": [], "summary": "博查key未配置", "source": "bocha_chinese"}
    try:
        resp = httpx.post(BOCHA_URL, json={
            "query": query, "freshness": "oneYear", "summary": True, "count": min(limit, 10),
        }, headers={"Authorization": f"Bearer {BOCHA_KEY}", "Content-Type": "application/json"}, timeout=15)
        data = resp.json()
        body = data.get("data", data)  # 博查返回 {"code":200, "data":{...}}

        web_pages = body.get("webPages", {}).get("value", [])
        snippets = []
        for page in web_pages[:limit]:
            title = page.get("name", "")
            url = page.get("url", "")
            snippet = page.get("snippet", "")
            summary_text = page.get("summary", "")
            text = summary_text if summary_text else snippet
            snippets.append(f"[{title}]({url}): {text[:200]}")

        first_summary = web_pages[0].get("summary", "") if web_pages else ""
        summary = first_summary[:500] if first_summary else f"博查搜索'{query}'返回{len(web_pages)}条结果"

        return {
            "tool": "bocha_search", "query": query, "results_count": len(web_pages),
            "summary": summary, "snippets": snippets[:5], "raw_results": web_pages[:limit],
            "source": "bocha_chinese",
        }
    except Exception as e:
        logger.error(f"bocha_search failed: {e}")
        return {"tool": "bocha_search", "query": query, "error": str(e), "summary": "博查出错", "snippets": [], "source": "bocha_chinese"}


def _image_generate(params: dict) -> dict:
    """豆包Seedream文生图"""
    prompt = params.get("prompt", params.get("query", ""))
    size = params.get("size", "2K")
    result = generate_image(prompt, size)
    result["tool"] = "image_generate"
    return result
