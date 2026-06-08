"""
IntentRegistry — 意图元数据中心

新增意图只需在此注册一个条目，所有模块自动识别。
"""
from enum import IntEnum


class Complexity(IntEnum):
    SIMPLE = 1
    MEDIUM = 2
    COMPLEX = 3

# ============================================================
# 意图注册表 — 唯一真相来源 (Single Source of Truth)
# ============================================================
# 每个意图包含：路由、名称、复杂度、DAG模板、拆解规则、校验规则
# 新增意图只需加一个条目，无需改任何其他文件

INTENT_REGISTRY = {
    "selection": {
        "mode": "selection",
        "name": "单品选品分析",
        "display": "智能选品",
        "complexity": Complexity.COMPLEX,
        "decompose_rule": "分析单品类市场机会。聚焦：市场搜索趋势判断、价格段分布、竞品格局。根据实际需求选择必要工具，避免全用。不需要同时搜中文和英文，选bocha_search即可。",
        "intent_signals": ["选品", "分析", "机会", "报告"],
        "precheck": ["require_analysis_object"],
        "relevant_tools": ["bocha_search", "web_search", "trend_analyze",
                          "price_analyze", "competitive_analyze",
                          "scoring_engine", "report_generate"],
        "dag": {
            "description": "双源并行搜索→趋势/价格/竞品提取→评分→报告",
            "tasks": [
                {"id": "T1", "desc": "Tavily搜索品类数据", "tool": "web_search", "deps": [], "parallel_group": 0},
                {"id": "T1b", "desc": "博查搜索中文电商数据", "tool": "bocha_search", "deps": [], "parallel_group": 0},
                {"id": "T2", "desc": "LLM提取趋势洞察", "tool": "trend_analyze", "deps": ["T1", "T1b"], "parallel_group": 1},
                {"id": "T3", "desc": "LLM提取价格带分析", "tool": "price_analyze", "deps": ["T1", "T1b"], "parallel_group": 1},
                {"id": "T4", "desc": "LLM提取竞品格局", "tool": "competitive_analyze", "deps": ["T1", "T1b"], "parallel_group": 1},
                {"id": "T5", "desc": "LLM多维度综合评分", "tool": "scoring_engine", "deps": ["T2", "T3", "T4"], "parallel_group": 2},
                {"id": "T6", "desc": "生成选品报告", "tool": "report_generate", "deps": ["T5"], "parallel_group": 2},
            ],
            "dag_structure": "(T1∥T1b)→(T2∥T3∥T4)→T5→T6",
        },
    },
    "competitive": {
        "mode": "competitive",
        "name": "多品牌竞品对标",
        "display": "竞品对标",
        "complexity": Complexity.COMPLEX,
        "decompose_rule": "对比两个品牌的同类产品。聚焦：双方搜索对比、核心指标提取、SWOT各维度。不需要趋势分析和评分，重点是差异化。",
        "intent_signals": ["对比", "对标", "竞品", "比较", "vs"],
        "precheck": ["require_analysis_object", "require_brands"],
        "relevant_tools": ["bocha_search", "web_search", "competitive_analyze", "report_generate"],
        "dag": {
            "description": "博查双品牌搜索+Tavily兜底→对比分析→SWOT→报告",
            "tasks": [
                {"id": "T1", "desc": "博查搜索品牌对比", "tool": "bocha_search", "deps": [], "parallel_group": 0},
                {"id": "T2", "desc": "博查搜索品牌A", "tool": "bocha_search", "deps": [], "parallel_group": 0},
                {"id": "T3", "desc": "博查搜索品牌B", "tool": "bocha_search", "deps": [], "parallel_group": 0},
                {"id": "T1b", "desc": "Tavily兜底搜索", "tool": "web_search", "deps": [], "parallel_group": 0},
                {"id": "T4", "desc": "LLM竞品对比分析", "tool": "competitive_analyze", "deps": ["T1", "T2", "T3", "T1b"], "parallel_group": 1},
                {"id": "T5", "desc": "LLM提取价格对比", "tool": "price_analyze", "deps": ["T1", "T2", "T3", "T1b"], "parallel_group": 1},
                {"id": "T6", "desc": "生成竞品对标报告", "tool": "report_generate", "deps": ["T4", "T5"], "parallel_group": 2},
            ],
            "dag_structure": "(T1∥T2∥T3∥T1b)→(T4∥T5)→T6",
        },
    },
    "trend": {
        "mode": "trend",
        "name": "品类趋势洞察",
        "display": "趋势洞察",
        "complexity": Complexity.MEDIUM,
        "decompose_rule": "洞察品类流行趋势。聚焦：趋势搜索提取方向判断热度排序。不需要价格或竞品分析。工具尽量精约。",
        "intent_signals": ["趋势", "流行", "洞察", "方向", "面料趋势", "廓形", "色彩"],
        "precheck": ["require_analysis_object"],
        "relevant_tools": ["bocha_search", "web_search", "trend_analyze", "report_generate"],
        "dag": {
            "description": "博查搜索+Tavily兜底→提取→排序→报告",
            "tasks": [
                {"id": "T1", "desc": "博查搜索品类趋势", "tool": "bocha_search", "deps": [], "parallel_group": 0},
                {"id": "T1b", "desc": "Tavily兜底搜索趋势", "tool": "web_search", "deps": [], "parallel_group": 0},
                {"id": "T2", "desc": "LLM提取趋势方向", "tool": "trend_analyze", "deps": ["T1", "T1b"], "parallel_group": 1},
                {"id": "T3", "desc": "LLM热度排序", "tool": "scoring_engine", "deps": ["T2"], "parallel_group": 2},
                {"id": "T4", "desc": "生成趋势报告", "tool": "report_generate", "deps": ["T3"], "parallel_group": 2},
            ],
            "dag_structure": "(T1∥T1b)→T2→T3→T4",
        },
    },
    "copy": {
        "mode": "copy",
        "name": "商品文案生成",
        "display": "文案生成",
        "complexity": Complexity.SIMPLE,
        "decompose_rule": "生成电商商品文案。只需搜索关键词卖点后直接生成文案。绝对不要趋势/价格/竞品任何分析工具。",
        "intent_signals": ["文案", "标题", "详情页", "种草", "口播", "淘宝标题"],
        "precheck": ["require_analysis_object"],
        "relevant_tools": ["bocha_search", "web_search", "report_generate"],
        "dag": {
            "description": "博查搜索热搜词→直接生成文案",
            "tasks": [
                {"id": "T1", "desc": "博查搜索热搜词和竞品文案", "tool": "bocha_search", "deps": [], "parallel_group": 0},
                {"id": "T1b", "desc": "Tavily兜底搜索参考", "tool": "web_search", "deps": [], "parallel_group": 0},
                {"id": "T2", "desc": "生成多平台文案", "tool": "report_generate", "deps": ["T1", "T1b"], "parallel_group": 1},
            ],
            "dag_structure": "(T1∥T1b)→T2",
        },
    },
    "pricing": {
        "mode": "pricing",
        "name": "定价策略分析",
        "display": "定价策略",
        "complexity": Complexity.MEDIUM,
        "decompose_rule": "分析品类定价策略。聚焦：价格段分布搜索成本分析竞品定价参考。根据情况选必要工具。",
        "intent_signals": ["定价", "价格策略", "价格带", "成本", "利润"],
        "precheck": ["require_analysis_object"],
        "relevant_tools": ["bocha_search", "web_search", "price_analyze",
                          "competitive_analyze", "report_generate"],
        "dag": {
            "description": "博查搜索+Tavily兜底→价格/竞品分析→报告",
            "tasks": [
                {"id": "T1", "desc": "博查搜索品类价格带", "tool": "bocha_search", "deps": [], "parallel_group": 0},
                {"id": "T1b", "desc": "Tavily兜底搜索价格", "tool": "web_search", "deps": [], "parallel_group": 0},
                {"id": "T2", "desc": "LLM提取价格分布", "tool": "price_analyze", "deps": ["T1", "T1b"], "parallel_group": 1},
                {"id": "T3", "desc": "LLM竞品定价分析", "tool": "competitive_analyze", "deps": ["T1", "T1b"], "parallel_group": 1},
                {"id": "T4", "desc": "生成定价策略报告", "tool": "report_generate", "deps": ["T2", "T3"], "parallel_group": 2},
            ],
            "dag_structure": "(T1∥T1b)→(T2∥T3)→T4",
        },
    },
    "launch": {
        "mode": "launch",
        "name": "上新排期优化",
        "display": "上新排期",
        "complexity": Complexity.MEDIUM,
        "decompose_rule": "规划服装上新排期。聚焦：趋势搜索回顾日历搜索节点后分析最佳窗口。不需要竞品或价格分析。",
        "intent_signals": ["上新", "排期", "日历", "大促", "618", "双11", "测款"],
        "precheck": ["require_analysis_object"],
        "relevant_tools": ["bocha_search", "web_search", "report_generate"],
        "dag": {
            "description": "博查双搜索+Tavily兜底→趋势→报告",
            "tasks": [
                {"id": "T1", "desc": "博查搜索季节趋势", "tool": "bocha_search", "deps": [], "parallel_group": 0},
                {"id": "T2", "desc": "博查搜索大促日历", "tool": "bocha_search", "deps": [], "parallel_group": 0},
                {"id": "T1b", "desc": "Tavily兜底搜索", "tool": "web_search", "deps": [], "parallel_group": 0},
                {"id": "T3", "desc": "LLM提取趋势洞察", "tool": "trend_analyze", "deps": ["T1", "T1b"], "parallel_group": 1},
                {"id": "T4", "desc": "生成排期报告", "tool": "report_generate", "deps": ["T2", "T3"], "parallel_group": 2},
            ],
            "dag_structure": "(T1∥T2∥T1b)→T3→T4",
        },
    },
    "image": {
        "mode": "image",
        "name": "文生图",
        "display": "文生图",
        "complexity": Complexity.SIMPLE,
        "decompose_rule": "跳过拆解，直接用固定模板（生成任务，非推理任务）",
        "intent_signals": ["生成", "设计图", "图片", "摄影图", "产品图", "拍照", "拍摄", "照片", "海报", "模特图"],
        "precheck": ["image_quality"],
        "relevant_tools": ["image_generate"],
        "skip_decompose": True,
        "dag": {
            "description": "文生图DAG：生成图片",
            "tasks": [
                {"id": "T1", "desc": "生成图片", "tool": "image_generate", "deps": [], "parallel_group": 0},
            ],
            "dag_structure": "T1",
        },
    },
    "unknown": {
        "mode": "unknown",
        "name": "无法识别",
        "display": "无法识别",
        "complexity": Complexity.SIMPLE,
        "decompose_rule": "无需拆解，直接返回无法识别的提示",
        "intent_signals": [],
        "precheck": [],
        "relevant_tools": [],
        "skip_decompose": True,
        "dag": {
            "description": "无法识别：直接返回友好提示",
            "tasks": [],
            "dag_structure": "N/A",
        },
    },
}

# ============================================================
# 便捷查询函数
# ============================================================

def get_all_modes() -> list[str]:
    return list(INTENT_REGISTRY.keys())

def get_mode(name: str) -> str | None:
    """中文名 → mode key"""
    for mode, info in INTENT_REGISTRY.items():
        if info["name"] == name:
            return mode
    return None

def get_name(mode: str) -> str:
    """mode key → 中文名"""
    return INTENT_REGISTRY.get(mode, {}).get("name", mode)

def get_complexity(mode: str) -> Complexity:
    return INTENT_REGISTRY.get(mode, {}).get("complexity", Complexity.MEDIUM)

def get_dag(mode: str) -> dict | None:
    return INTENT_REGISTRY.get(mode, {}).get("dag")

def get_decompose_rule(mode: str) -> str:
    return INTENT_REGISTRY.get(mode, {}).get("decompose_rule", "分析→报告")

def get_intent_signals(mode: str) -> list[str]:
    return INTENT_REGISTRY.get(mode, {}).get("intent_signals", [])

def get_display_name(mode: str) -> str:
    return INTENT_REGISTRY.get(mode, {}).get("display", mode)

def route_by_name(cn_name: str) -> str:
    """中文意图名 → mode key"""
    for mode, info in INTENT_REGISTRY.items():
        if info["name"] == cn_name or cn_name in info["name"]:
            return mode
    return "selection"

def get_all_names() -> dict[str, str]:
    """{mode: name} 映射"""
    return {mode: info["name"] for mode, info in INTENT_REGISTRY.items()}

def get_en_to_cn() -> dict[str, str]:
    """英文mode → 中文名映射（兼容旧代码）"""
    return {mode: info["name"] for mode, info in INTENT_REGISTRY.items()
            if mode != "image"}  # image 是中文直接用

def get_mode_fallback() -> dict[str, str]:
    """mode → 中文名 fallback"""
    return {mode: info["name"] for mode, info in INTENT_REGISTRY.items()}

def get_all_dags() -> dict:
    """{mode: dag_dict}"""
    return {mode: info["dag"] for mode, info in INTENT_REGISTRY.items()}
