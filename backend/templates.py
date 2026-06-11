"""
TemplateRegistry — 报告模板注册表

所有报告模板集中在此，按意图分组。每个模板包含：
  - id: 唯一标识（"{intent_mode}-{variant}"）
  - name: 显示名
  - description: 简短说明
  - intent: 所属意图 mode
  - prompt_builder: 构建 prompt 的函数
  - sections_summary: sections 概览（前端展示用）

新增模板只需在此加一个条目，report.py 自动发现。
"""
import logging
from typing import Optional

from .intent import goal_to_text

logger = logging.getLogger(__name__)

# ── 共享 JSON Schema（所有模板共用） ──
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


# ══════════════════════════════════════════════════
#  Prompt 构建函数（每个模板一个）
# ══════════════════════════════════════════════════

def _prompt_base(prompt_body: str, schema: str = _SCHEMA) -> str:
    """基础 prompt 包装器 — 注入 schema"""
    return prompt_body + "\n\n" + schema


# ── 选品分析 ──

def _selection_standard(goal, intent_type, data, memory, extra):
    return _prompt_base(f"""你是服饰电商选品分析师。基于搜索数据生成选品分析JSON报告。

任务: {intent_type}
用户需求: {goal_to_text(goal)}
{memory}{data}{extra}

报告结构（按顺序填入 sections 数组）：
1. 数据总览 — metrics（3-4个指标：搜索热度/竞争强度/利润空间/趋势匹配度）
2. 趋势方向 — section_title + insight.tip ×2-3条
3. 价格带分析 — section_title + bar_chart（3-5个价格带，c1/c2/c3三色）
4. 竞品格局 — section_title + table（品牌|定位|价格带|优势|劣势）
5. TOP选品方向 — section_title + brand_card ×2-3个
6. 避坑建议 — insight.warn""")


def _selection_douyin(goal, intent_type, data, memory, extra):
    return _prompt_base(f"""你是服饰电商选品分析师，专注**抖音电商**场景。基于搜索数据生成选品分析JSON报告。

任务: {intent_type}
用户需求: {goal_to_text(goal)}
{memory}{data}{extra}

报告结构（按顺序）：
1. 热度指标 — metrics（视频播放热度/达人合作密度/内容挂车率/搜索增长趋势）
2. 爆款分析 — brand_card ×2（近期销量高的款式+价格+内容特征）
3. 内容方向 — insight.tip ×2（什么样的内容容易爆）
4. 达人生态 — table（达人类型|粉丝量|带货力|内容风格）
5. 选品建议 — section_title + brand_card ×2-3个
6. 风险提示 — insight.warn""")


# ── 竞品对标 ──

def _competitive_standard(goal, intent_type, data, memory, extra):
    return _prompt_base(f"""你是服饰电商竞品分析师。基于搜索数据生成竞品对标JSON报告。

任务: {intent_type}
用户需求: {goal_to_text(goal)}
{memory}{data}{extra}

报告结构（按顺序）：
1. 品牌概览 — compare（定位/价格带/风格/渠道）
2. 核心指标对比 — section_title + metrics（均价/SKU数/店铺评分/搜索热度，用accent区分品牌）
3. 价格带对比 — section_title + bar_chart（每个品牌每个价格带一行，c1=品牌A, c2=品牌B）
4. 面料策略对比 — section_title + table（维度|品牌A|品牌B）
5. 设计风格对比 — section_title + table
6. SWOT矩阵 — swot ×2（brand_a和brand_b各一个）
7. 差异化机会 — insight.tip""")


def _competitive_quick(goal, intent_type, data, memory, extra):
    return _prompt_base(f"""你是服饰电商竞品分析师。基于搜索数据生成**精简短报告**。

任务: {intent_type}
用户需求: {goal_to_text(goal)}
{memory}{data}{extra}

报告结构（按顺序）— 请精简，控制在4个section以内：
1. 核心差异 — compare（定位/价格带/风格/渠道）
2. 关键指标对比 — section_title + metrics（均价/SKU数/评分，每个品牌一个指标卡）
3. SWOT矩阵 — swot ×2（各品牌一个）
4. 核心结论 — insight.tip（一句话机会点）

请专注于最重要的差异化维度，不要面面俱到。""")


# ── 趋势洞察 ──

def _trend_standard(goal, intent_type, data, memory, extra):
    return _prompt_base(f"""你是服饰电商趋势分析师。生成趋势洞察JSON报告。

任务: {intent_type}
用户需求: {goal_to_text(goal)}
{memory}{data}{extra}

报告结构：
1. 趋势热度排行 — section_title + bar_chart（3-5个方向，c1/c2/c3）
2. 面料趋势 — section_title + table（面料|热度|适用品类）
3. 廓形趋势 — section_title + table（廓形|热度|代表品牌）
4. 色彩趋势 — section_title + metrics（3-4个色系）+ table
5. 选品建议 — section_title + brand_card ×2-3个""")


# ── 文案生成 ──

def _copy_standard(goal, intent_type, data, memory, extra):
    return _prompt_base(f"""你是资深电商文案策划。直接生成商品文案JSON报告，不做任何市场分析。

任务: {intent_type}
商品信息: {goal_to_text(goal)}
{data}

报告结构：
1. 核心关键词 — metrics（3-4个搜索热度关键词）
2. 淘宝标题 — section_title + insight.tip ×2-3个（标注字符数）
3. 详情页卖点 — section_title + table（卖点维度|文案内容）
4. 抖音口播 — section_title + text（完整口播文案）
5. 小红书种草 — section_title + text（正文+话题标签）""")


def _copy_xiaohongshu(goal, intent_type, data, memory, extra):
    return _prompt_base(f"""你是资深小红书服饰种草文案策划。直接生成小红书风格文案JSON报告。

任务: {intent_type}
商品信息: {goal_to_text(goal)}
{data}

报告结构：
1. 核心关键词 — metrics（3-4个热搜词，侧重小红书热搜）
2. 小红书标题 — section_title + insight.tip ×3（含话题标签，emoji风格）
3. 正文内容 — section_title + text（完整种草文案，含场景代入感，300-500字）
4. 话题标签 — section_title + table（话题|搜索量预估|推荐度）
5. 发布时间建议 — insight.tip

注意：
- 语气轻松亲切，多用emoji，短句分段
- 标题控制在20字以内+话题标签
- 突出场景感而非卖货感
- 不要淘宝标题和抖音口播内容""")


# ── 定价策略 ──

def _pricing_standard(goal, intent_type, data, memory, extra):
    return _prompt_base(f"""你是服饰电商定价策略师。生成定价策略JSON报告。

任务: {intent_type}
用户需求: {goal_to_text(goal)}
{memory}{data}{extra}

报告结构：
1. 价格带分布 — section_title + bar_chart（3-5个区间，c1/c2/c3）
2. 竞品定价对比 — section_title + table（品牌|引流款|利润款|形象款）
3. 成本利润测算 — section_title + metrics（3-4项成本）
4. 定价建议 — section_title + brand_card ×3（引流款/利润款/形象款）
5. 促销节奏 — insight.tip""")


# ── 上新排期 ──

def _launch_standard(goal, intent_type, data, memory, extra):
    return _prompt_base(f"""你是服饰电商运营专家。生成上新排期JSON报告。

任务: {intent_type}
用户需求: {goal_to_text(goal)}
{memory}{data}{extra}

报告结构：
1. 品类季节曲线 — section_title + bar_chart（1-12月热度，c1淡季/c2旺季）
2. 大促日历 — section_title + table（节点|日期|折扣建议|备货提前期）
3. 最佳上新窗口 — section_title + metrics（3个窗口）
4. 测款节奏 — insight.tip
5. 风险日历 — insight.danger""")


# ══════════════════════════════════════════════════
#  模板注册表
# ══════════════════════════════════════════════════
# 每意图至少有一个 "standard" 模板作为默认值
# variant = "standard" 的模板是当前默认行为

TEMPLATE_REGISTRY = {
    # ── 选品分析 ──
    "selection-standard": {
        "id": "selection-standard",
        "name": "标准版",
        "description": "搜索热度/价格带/竞品格局/选品建议",
        "intent": "selection",
        "prompt_builder": _selection_standard,
    },
    "selection-douyin": {
        "id": "selection-douyin",
        "name": "抖音电商版",
        "description": "侧重视频带货热度、达人生态、内容方向分析",
        "intent": "selection",
        "prompt_builder": _selection_douyin,
    },

    # ── 竞品对标 ──
    "competitive-standard": {
        "id": "competitive-standard",
        "name": "标准版",
        "description": "品牌对比/指标/面料/设计/SWOT/结论",
        "intent": "competitive",
        "prompt_builder": _competitive_standard,
    },
    "competitive-quick": {
        "id": "competitive-quick",
        "name": "快速版",
        "description": "精简为4个section，聚焦核心差异和结论",
        "intent": "competitive",
        "prompt_builder": _competitive_quick,
    },

    # ── 趋势洞察 ──
    "trend-standard": {
        "id": "trend-standard",
        "name": "标准版",
        "description": "热度排行/面料/廓形/色彩/选品建议",
        "intent": "trend",
        "prompt_builder": _trend_standard,
    },

    # ── 文案生成 ──
    "copy-standard": {
        "id": "copy-standard",
        "name": "标准版",
        "description": "淘宝标题+详情页卖点+抖音口播+小红书种草",
        "intent": "copy",
        "prompt_builder": _copy_standard,
    },
    "copy-xiaohongshu": {
        "id": "copy-xiaohongshu",
        "name": "小红书版",
        "description": "专注小红书种草风格，不含淘宝/抖音内容",
        "intent": "copy",
        "prompt_builder": _copy_xiaohongshu,
    },

    # ── 定价策略 ──
    "pricing-standard": {
        "id": "pricing-standard",
        "name": "标准版",
        "description": "价格带分布/竞品对比/成本利润/定价建议",
        "intent": "pricing",
        "prompt_builder": _pricing_standard,
    },

    # ── 上新排期 ──
    "launch-standard": {
        "id": "launch-standard",
        "name": "标准版",
        "description": "季节曲线/大促日历/上新窗口/测款/风险",
        "intent": "launch",
        "prompt_builder": _launch_standard,
    },
}


# ══════════════════════════════════════════════════
#  查询函数
# ══════════════════════════════════════════════════

def get_template(template_id: str) -> Optional[dict]:
    """获取模板定义，不存在返回 None"""
    return TEMPLATE_REGISTRY.get(template_id)


def get_templates_for_intent(intent_mode: str) -> list[dict]:
    """获取某意图的所有可用模板（不含 prompt_builder，前端使用）"""
    return [
        {"id": t["id"], "name": t["name"],
         "description": t["description"], "intent": t["intent"]}
        for t in TEMPLATE_REGISTRY.values()
        if t["intent"] == intent_mode
    ]


def resolve_template(intent_mode: str, template_id: str = None) -> dict:
    """解析模板：template_id → 模板定义。未指定或不存在时返回 standard"""
    if template_id:
        tpl = get_template(template_id)
        if tpl and tpl["intent"] == intent_mode:
            return tpl
        logger.warning(f"Template '{template_id}' not found for intent '{intent_mode}', fallback to standard")
    # 降级到 standard
    std_id = f"{intent_mode}-standard"
    std = get_template(std_id)
    if std:
        return std
    # 兜底：如果连 standard 都没有（新增意图时），返回第一个可用
    available = get_templates_for_intent(intent_mode)
    if available:
        fallback = get_template(available[0]["id"])
        if fallback:
            return fallback
    raise ValueError(f"No templates found for intent '{intent_mode}'")


def list_all_templates() -> list[dict]:
    """返回所有模板元数据（无 prompt_builder）"""
    return [
        {"id": t["id"], "name": t["name"],
         "description": t["description"], "intent": t["intent"]}
        for t in TEMPLATE_REGISTRY.values()
    ]
