"""
Agent Engine v8: Harness架构 + 动态路由 + 多轮对话 + 增强记忆

Pipeline:
  Phase 0: 场景检测 (多轮对话) → 查询增强
  Phase 1: 意图识别 (deepseek-chat, ~1-3s)
  Phase 2: 前置校验 (规则引擎 + 澄清交互)
  Phase 3: DAG拆解 (deepseek-v4-pro, CostRouter控制)
  Phase 4-5: 工具映射+并行执行 (ParallelExecutor)
  Phase 6: 报告生成 (deepseek-chat)
  Phase 7: 反思修正 (CostRouter控制是否执行)

v8 变更:
  - Pipeline Harness: ToolRegistry / DAGLoader / ParallelExecutor / TraceCollector
  - CostRouter: 动态路由，简单查询跳过重量工具和反思
  - WorkingMemory: 结构化主题上下文 + 分析历史 + 偏好累积
  - ConversationManager: 多轮场景检测 + 查询增强
"""
import json
import re
import asyncio
import logging
import time
from typing import AsyncGenerator
from pathlib import Path

# Harness层
try:
    from .harness.registry import get_registry
    from .harness.dag_loader import get_dag_loader
    from .harness.router import get_router, Complexity
    from .harness.tracer import get_tracer
    from .harness.executor import ParallelExecutor
    from .conversation import get_conversation_manager, Scenario
    from .llm_client import chat, extract_json, MODEL_FLASH, MODEL_PRO, MODEL_CHAT
    from .memory import MemorySystem
    from .tools import execute_tool_sync, AVAILABLE_TOOLS
    from .intent import IntentRouter
    from .report import ReportBuilder
    from .reflect import ReflectionEngine
    from .image_optimizer import ImageOptimizer
    from .precheck import PrecheckEngine
    from .observability import get_metrics
    from .intent_registry import get_decompose_rule, get_all_names
    from .decompose_engine import DecomposeEngine
except ImportError:
    from harness.registry import get_registry
    from harness.dag_loader import get_dag_loader
    from harness.router import get_router, Complexity
    from harness.tracer import get_tracer
    from harness.executor import ParallelExecutor
    from conversation import get_conversation_manager, Scenario
    from llm_client import chat, extract_json, MODEL_FLASH, MODEL_PRO, MODEL_CHAT
    from memory import MemorySystem
    from tools import execute_tool_sync, AVAILABLE_TOOLS
    from intent import IntentRouter
    from report import ReportBuilder
    from reflect import ReflectionEngine
    from image_optimizer import ImageOptimizer
    from precheck import PrecheckEngine
    from observability import get_metrics
    from intent_registry import get_decompose_rule, get_all_names
    from decompose_engine import DecomposeEngine

logger = logging.getLogger(__name__)

# 数据目录
DATA_DIR = Path(__file__).parent.parent / "data"

# 工具注册中心（从tools.py同步）


# ============ 意图→DAG模板映射 (P2) ============
DAG_TEMPLATES = {
    "selection": {
        "description": "选品分析DAG：双源并行搜索(Tavily+博查)→趋势/价格/竞品并行提取→综合评分→报告",
        "tasks": [
            {"id": "T1", "desc": "Tavily搜索目标品类数据", "tool": "web_search", "deps": [], "parallel_group": 0},
            {"id": "T1b", "desc": "博查搜索中文电商数据", "tool": "bocha_search", "deps": [], "parallel_group": 0},
            {"id": "T2", "desc": "LLM提取趋势洞察", "tool": "trend_analyze", "deps": ["T1", "T1b"], "parallel_group": 1},
            {"id": "T3", "desc": "LLM提取价格带分析", "tool": "price_analyze", "deps": ["T1", "T1b"], "parallel_group": 1},
            {"id": "T4", "desc": "LLM提取竞品格局", "tool": "competitive_analyze", "deps": ["T1", "T1b"], "parallel_group": 1},
            {"id": "T5", "desc": "LLM多维度综合评分", "tool": "scoring_engine", "deps": ["T2", "T3", "T4"], "parallel_group": 2},
            {"id": "T6", "desc": "生成选品报告", "tool": "report_generate", "deps": ["T5"], "parallel_group": 2},
        ],
        "dag_structure": "(T1∥T1b)→(T2∥T3∥T4)→T5→T6",
    },
    "competitive": {
        "description": "竞品对标DAG：博查双品牌搜索+Tavily兜底→对比分析→SWOT→报告",
        "tasks": [
            {"id": "T1", "desc": "博查搜索：品牌A 品牌B 连衣裙 对比 价格 面料 风格", "tool": "bocha_search", "deps": [], "parallel_group": 0},
            {"id": "T2", "desc": "博查搜索：品牌A 2026夏季 连衣裙 新品 价格", "tool": "bocha_search", "deps": [], "parallel_group": 0},
            {"id": "T3", "desc": "博查搜索：品牌B 2026夏季 连衣裙 新品 价格", "tool": "bocha_search", "deps": [], "parallel_group": 0},
            {"id": "T1b", "desc": "Tavily兜底搜索品牌对比", "tool": "web_search", "deps": [], "parallel_group": 0},
            {"id": "T4", "desc": "LLM竞品对比分析", "tool": "competitive_analyze", "deps": ["T1", "T2", "T3", "T1b"], "parallel_group": 1},
            {"id": "T5", "desc": "LLM提取价格对比", "tool": "price_analyze", "deps": ["T1", "T2", "T3", "T1b"], "parallel_group": 1},
            {"id": "T6", "desc": "生成竞品对标报告", "tool": "report_generate", "deps": ["T4", "T5"], "parallel_group": 2},
        ],
        "dag_structure": "(T1∥T2∥T3∥T1b)→(T4∥T5)→T6",
    },
    "trend": {
        "description": "趋势洞察DAG：博查搜索+Tavily兜底→LLM提取→热度排序→报告",
        "tasks": [
            {"id": "T1", "desc": "博查搜索品类趋势", "tool": "bocha_search", "deps": [], "parallel_group": 0},
            {"id": "T1b", "desc": "Tavily兜底搜索趋势", "tool": "web_search", "deps": [], "parallel_group": 0},
            {"id": "T2", "desc": "LLM提取趋势方向", "tool": "trend_analyze", "deps": ["T1", "T1b"], "parallel_group": 1},
            {"id": "T3", "desc": "LLM趋势热度排序", "tool": "scoring_engine", "deps": ["T2"], "parallel_group": 2},
            {"id": "T4", "desc": "生成趋势洞察报告", "tool": "report_generate", "deps": ["T3"], "parallel_group": 2},
        ],
        "dag_structure": "(T1∥T1b)→T2→T3→T4",
    },
    "copy": {
        "description": "文案生成DAG：博查搜索+Tavily兜底→LLM卖点→多平台文案",
        "tasks": [
            {"id": "T1", "desc": "博查搜索热搜词和竞品文案", "tool": "bocha_search", "deps": [], "parallel_group": 0},
            {"id": "T1b", "desc": "Tavily兜底搜索文案参考", "tool": "web_search", "deps": [], "parallel_group": 0},
            {"id": "T2", "desc": "LLM提取卖点洞察", "tool": "trend_analyze", "deps": ["T1", "T1b"], "parallel_group": 1},
            {"id": "T3", "desc": "生成多平台文案", "tool": "report_generate", "deps": ["T2"], "parallel_group": 2},
        ],
        "dag_structure": "(T1∥T1b)→T2→T3",
    },
    "pricing": {
        "description": "定价策略DAG：博查搜索+Tavily兜底→LLM价格/竞品分析→报告",
        "tasks": [
            {"id": "T1", "desc": "博查搜索品类价格带", "tool": "bocha_search", "deps": [], "parallel_group": 0},
            {"id": "T1b", "desc": "Tavily兜底搜索价格参考", "tool": "web_search", "deps": [], "parallel_group": 0},
            {"id": "T2", "desc": "LLM提取价格分布", "tool": "price_analyze", "deps": ["T1", "T1b"], "parallel_group": 1},
            {"id": "T3", "desc": "LLM竞品定价分析", "tool": "competitive_analyze", "deps": ["T1", "T1b"], "parallel_group": 1},
            {"id": "T4", "desc": "生成定价策略报告", "tool": "report_generate", "deps": ["T2", "T3"], "parallel_group": 2},
        ],
        "dag_structure": "(T1∥T1b)→(T2∥T3)→T4",
    },
    "launch": {
        "description": "上新排期DAG：博查双源搜索+Tavily兜底→窗口分析→排期建议",
        "tasks": [
            {"id": "T1", "desc": "博查搜索品类季节趋势", "tool": "bocha_search", "deps": [], "parallel_group": 0},
            {"id": "T2", "desc": "博查搜索平台大促日历", "tool": "bocha_search", "deps": [], "parallel_group": 0},
            {"id": "T1b", "desc": "Tavily兜底搜索趋势+日历", "tool": "web_search", "deps": [], "parallel_group": 0},
            {"id": "T3", "desc": "LLM提取趋势洞察", "tool": "trend_analyze", "deps": ["T1", "T1b"], "parallel_group": 1},
            {"id": "T4", "desc": "生成排期建议报告", "tool": "report_generate", "deps": ["T2", "T3"], "parallel_group": 2},
        ],
        "dag_structure": "(T1∥T2∥T1b)→T3→T4",
    },
    "image": {
        "description": "文生图DAG：生成图片",
        "tasks": [
            {"id": "T1", "desc": "生成图片", "tool": "image_generate", "deps": [], "parallel_group": 0},
        ],
        "dag_structure": "T1",
    },
}

# ============ 报告模板 (按意图差异化) ============
REPORT_TEMPLATES = {
    "selection": """生成选品分析报告。使用以下视觉组件规范：

【数据总览】用 rc-metrics 卡片行展示：搜索热度指数 / 竞争强度 / 利润空间预估 / 趋势匹配度
【价格带分析】用 rc-bar-chart 柱状图展示各价格带占比（c1/c2/c3三色），底部标注主力区间
【趋势方向】用 rc-section-title 分区标题分隔，每个趋势方向用 rc-insight.tip 展示，含热度评分
【竞品格局】用 rc-table 对比表格，列：品牌/定位/价格带/优势/劣势
【TOP选品方向】用 rc-brand-card 卡片展示（5个方向），每个卡片含建议价格+推荐理由+风险提示
【避坑建议】用 rc-insight.warn 红色警示框

HTML格式，使用上述class，不生成style/head/body标签。数据驱动，每个结论标注置信度。""",

    "competitive": """生成竞品对标报告。使用以下视觉组件规范：

【品牌概览】用 rc-compare 左右对比卡片（brand-a品牌A / brand-b品牌B），每卡片含：定位/价格带/目标人群/风格关键词/面料策略/渠道优势
【核心指标对比】用 rc-metrics 卡片行展示：品牌A均价 vs 品牌B均价 / 连衣裙SKU数 / 天猫店铺评分
【价格带对比】用 rc-bar-chart 柱状图（双色c1/c2区分品牌），展示各品牌在不同价格区间的分布
【多维度对比】用 rc-table 表格：对比维度 | 品牌A | 品牌B | 差异分析
【SWOT分析】用 rc-swot 四宫格矩阵（两个品牌分别一个矩阵），每格含tag标签
【差异化机会】用 rc-insight.tip 绿色洞察框，含具体可执行的切入建议（价格锚点+设计元素+渠道策略）
【结论】用 rc-section-title.sage 分区标题，总结核心竞争格局+选哪个品牌策略更值得参考

HTML格式，使用上述class。品牌A用brand-a样式，品牌B用brand-b样式。""",

    "trend": """生成品类趋势洞察报告。使用以下视觉组件规范：

【趋势热度排行】用 rc-bar-chart 柱状图展示3-5个趋势方向的热度值（c1/c2/c3三色）
【趋势详情】每个趋势方向用 rc-section-title 分区标题 + rc-insight.tip 详细展开，含：关键证据/代表品牌/适用价格带/可持续性评估
【面料趋势】用 rc-table 表格：面料类型 | 热度趋势 | 适用品类 | 成本区间 | 采购建议
【风格&廓形】用 rc-metrics 卡片行展示关键数据
【消费者偏好】用 rc-insight.warn 展示需注意的偏好变化
【选品切入建议】用 rc-brand-card 卡片展示3个具体切入方向，含时间窗口

HTML格式，使用上述class。数据驱动。""",

    "copy": """生成多平台商品文案。使用以下视觉组件规范：

【淘宝搜索标题】用 rc-metric.accent-gold 大号展示，标注字符数和热搜词
【抖音口播脚本】用 rc-insight.tip 展示完整口播文案（含时间节点标记）
【小红书种草文案】用 rc-insight.tip 展示正文+话题标签
【详情页卖点提炼】用 rc-table 表格：卖点维度 | 文案内容 | 用户痛点对标
【多平台适配建议】用 rc-insight.warn 展示各平台差异注意事项
【SEO关键词】用 rc-metrics 卡片行展示核心关键词+搜索量预估

HTML格式，使用上述class。文案可直接使用，非描述性说明。""",

    "pricing": """生成定价策略报告。使用以下视觉组件规范：

【价格带分布】用 rc-bar-chart 柱状图展示品类价格带分布（c1/c2/c3三色，标注各区间占比）
【竞品定价对比】用 rc-table 表格：品牌 | 引流款价格 | 利润款价格 | 形象款价格 | 促销折扣力度
【成本利润测算】用 rc-metrics 卡片行：面料成本/加工费/平台扣点/物流/毛利率/净利率
【定价建议】用 rc-brand-card 三卡片展示引流款/利润款/形象款各自定价区间+理由
【促销节奏】用 rc-insight.tip 展示年度促销节点+建议折扣力度
【风险提示】用 rc-insight.danger 展示定价风险

HTML格式，使用上述class。所有价格用¥标注。""",

    "launch": """生成上新排期建议。使用以下视觉组件规范：

【品类季节曲线】用 rc-bar-chart 柱状图展示1-12月搜索热度趋势（c1/c2双色区分淡旺季）
【平台大促日历】用 rc-table 表格：大促节点 | 日期 | 适用品类 | 建议折扣 | 备货提前期
【最佳上新窗口】用 rc-metrics 卡片行展示3个最佳上新时间窗口+理由
【测款节奏】用 rc-insight.tip 展示测款→放量→清仓的时间节奏+各阶段运营重点
【库存深度规划】用 rc-insight.warn 展示不同款式的建议首单深度和补货周期
【风险日历】用 rc-insight.danger 标注需避开的时间窗口

HTML格式，使用上述class。""",
}


class AgentEngine:
    def __init__(self):
        self.memory = MemorySystem()
        self.registry = get_registry()
        self.executor = ParallelExecutor(execute_tool_sync)
        self.dag_loader = get_dag_loader()
        self.router = get_router()
        self.tracer = get_tracer()
        self.conversation = get_conversation_manager()
        self.intent_router = IntentRouter(self.memory)
        self.report_builder = ReportBuilder(self.memory)
        self.reflection_engine = ReflectionEngine()
        self.image_optimizer = ImageOptimizer()
        self.precheck = PrecheckEngine()
        self._pending_clarify = None
        self._report_cache = self._load_cache()
        self.decompose_engine = DecomposeEngine(self.dag_loader)

    async def run_pipeline(self, user_input: str, session_id: str, mode: str = "selection",
                           clarify_answer: str = None) -> AsyncGenerator[dict, None]:

        if clarify_answer and self._pending_clarify:
            user_input = f"{user_input}。补充说明: {clarify_answer}"
            self._pending_clarify = None

        trace_id = self.tracer.start(session_id, user_input)
        yield {"type": "phase", "phase": "start", "data": {"input": user_input, "session_id": session_id}}

        # ====== Phase 0: 多轮场景检测 + 实体提取 + 结构化 goal 合并 ======
        last_intent = self.memory.get_working_memory(session_id).get("last_intent", "")
        scenario = self.conversation.detect_scenario(user_input, last_intent)
        is_followup = self.conversation.is_followup(user_input)
        intent_modified = False
        changes = None
        if scenario != Scenario.NEW_QUERY:
            wm = self.memory.get_working_context(session_id)
            last_analysis = wm.get("last_analysis", {})
            if last_analysis:
                changes = self.conversation.extract_entities_from_followup(
                    user_input, last_analysis)
                if changes:
                    intent_modified = True
                    user_input = f"__followup_merge__{json.dumps(changes, ensure_ascii=False)}__"
            yield {"type": "phase", "phase": "conversation", "status": "done",
                   "data": {"scenario": scenario.name, "is_followup": is_followup,
                   "enhanced": intent_modified, "entity_changes": changes}}
            if not intent_modified:
                user_input = self.conversation.augment_query(user_input, scenario, wm)

        # ====== 缓存检查 (24h相同query命中, 在LLM调用前) ======
        cache_key = f"{user_input}|{mode or 'auto'}"
        if cache_key in self._report_cache:
            cached_time, cached_report = self._report_cache[cache_key]
            if time.time() - cached_time < 86400:
                yield {"type": "cache_hit", "data": {"cached": True, "age_hours": round((time.time()-cached_time)/3600, 1)}}
                yield {"type": "result", "content": cached_report}
                self.tracer.finish(trace_id, success=True)
                yield {"type": "summary", "data": get_metrics()}
                yield {"type": "done"}
                return

        # ====== Phase 1: LLM意图识别 + 工作记忆更新 ======
        yield {"type": "phase", "phase": "intent", "status": "running", "model": MODEL_FLASH}
        p_intent = self.intent_router.build_prompt(user_input, mode, session_id)
        yield {"type": "prompt", "phase": "intent", "model": MODEL_FLASH, "prompt": p_intent, "label": "Phase 1: 意图识别"}
        intent = await self.intent_router.classify(user_input, mode, session_id, prompt=p_intent)
        detected_mode = self.intent_router.route(intent)
        yield {"type": "phase", "phase": "intent", "status": "done",
               "data": {"intent": intent, "auto_routed": detected_mode}}

        # ====== Phase 1.2: 实体提取 — 追问合并到 intent.goal ======
        if intent_modified and changes:
            last_goal = intent.get("goal", {})
            merged_goal = self.conversation.merge_goal(last_goal, changes)
            intent["goal"] = merged_goal
            # 如果涉及意图切换，修正 intent_type
            if changes.get("intent_type"):
                intent["intent_type"] = changes["intent_type"]
                detected_mode = self.intent_router.route(intent)
                yield {"type": "phase", "phase": "router_redirect",
                       "status": "done", "data": {"old_mode": detected_mode,
                       "reason": f"追问切换意图至{changes['intent_type']}"}}
            # 重新生成 user_input 供缓存校验使用
            user_input = json.dumps(intent.get("goal", {}), ensure_ascii=False)

        # ====== Phase 1.5: 无法识别或置信度过低 → 直接返回友好提示 ======
        unknown_intent = detected_mode == "unknown"
        low_confidence = intent.get("confidence", 1.0) < 0.6 and detected_mode not in ("selection", "competitive", "image")
        if unknown_intent or low_confidence:
            report_text = json.dumps({
                "title": "无法识别您的需求",
                "sections": [{"type": "text", "data": {"content": "抱歉，我目前是服饰电商AI Agent，只能处理以下几种类型的问题：\n\n• 📊 选品分析 — 如\"分析2026夏季连衣裙选品机会\"\n• 🏷️ 竞品对标 — 如\"太平鸟vs伊芙丽对比\"\n• 📈 趋势洞察 — 如\"今年夏季连衣裙流行趋势\"\n• ✍️ 文案生成 — 如\"生成法式茶歇裙淘宝标题\"\n• 💰 定价策略 — 如\"连衣裙在天猫的定价策略\"\n• 📅 上新排期 — 如\"夏季连衣裙上新排期建议\"\n• 🎨 文生图 — 如\"生成法式碎花茶歇裙设计图\"\n\n请提供更具体的服饰电商相关需求。"}}]
            }, ensure_ascii=False)
            yield {"type": "result", "content": report_text}
            self.tracer.finish(trace_id, success=True)
            yield {"type": "summary", "data": get_metrics()}
            yield {"type": "done"}
            return

        # 更新工作记忆主题上下文
        self.memory.update_topic_context(session_id, intent)

        # CostRouter: 复杂度判定
        brands = intent.get("goal", {}).get("竞品品牌", []) or intent.get("entities", {}).get("brands", [])
        complexity = self.router.classify(user_input, intent.get("intent_type", ""), brands, is_followup)
        yield {"type": "phase", "phase": "router", "status": "done",
               "data": {"complexity": self.router.complexity_label(complexity),
               "include_reflection": self.router.should_include_reflection(complexity),
               "max_retries": self.router.get_max_retries(complexity)}}

        # ====== Phase 2: 前置校验 + 澄清 ======
        yield {"type": "phase", "phase": "precheck", "status": "running", "model": "rule_engine"}
        precheck = self.precheck.check(intent, user_input)
        yield {"type": "phase", "phase": "precheck", "status": "done", "data": precheck}

        gaps = precheck["checks"]["info_completeness"]["gaps"]
        if gaps and not clarify_answer:
            clarify_msg = self.precheck.build_clarify(gaps)
            self._pending_clarify = gaps
            yield {"type": "clarify", "message": clarify_msg, "gaps": gaps, "session_id": session_id}
            yield {"type": "done"}
            return

        # ====== Phase 3: DAG拆解 (image 是生成任务无需拆解，其余意图全部 LLM 拆解) ======
        _FIXED_DAG_MODES = {"image"}
        if detected_mode in _FIXED_DAG_MODES:
            template = self.dag_loader.load(detected_mode) or self.dag_loader.load("selection")
            tasks = [dict(t) for t in template["tasks"]]
            if detected_mode == "image":
                # 文生图：用LLM优化prompt注入到任务
                img_prompt = user_input or intent.get("goal", {}).get("核心关注点", "")
                p_img_opt = self.image_optimizer.build_prompt(img_prompt)
                yield {"type": "prompt", "phase": "image_optimize", "model": MODEL_FLASH, "prompt": p_img_opt, "label": "文生图 Prompt 优化"}
                optimized = await self.image_optimizer.optimize(img_prompt, prompt=p_img_opt)
                for t in tasks:
                    if t["tool"] == "image_generate":
                        t["desc"] = optimized
            dag = {"tasks": tasks, "dag_structure": template["dag_structure"]}
        else:
            yield {"type": "phase", "phase": "decompose", "status": "running", "model": MODEL_PRO}
            p_decompose = self.decompose_engine.build_prompt(intent, detected_mode)
            yield {"type": "prompt", "phase": "decompose", "model": MODEL_PRO, "prompt": p_decompose, "label": "Phase 3: DAG任务拆解"}
            dag = await self.decompose_engine.decompose(intent, detected_mode, prompt=p_decompose)
            yield {"type": "phase", "phase": "decompose", "status": "done", "data": dag}

        # ====== Phase 4: 工具映射 ======
        yield {"type": "phase", "phase": "tool_mapping", "status": "running", "model": "rule_engine"}
        mappings = self._map_tools(dag)
        yield {"type": "phase", "phase": "tool_mapping", "status": "done", "data": mappings}

        # ====== Phase 5: 并行执行 (ParallelExecutor) ======
        yield {"type": "phase", "phase": "execute", "status": "running", "model": "execution_engine"}
        exec_results = []
        async for step in self.executor.execute({"tasks": mappings.get("mappings", [])}):
            yield {"type": "phase", "phase": "execute", "status": "step", "data": step}
            # 工具层LLM调用：把prompt也发给前端
            tr = step.get("tool_result", {})
            if tr.get("_llm_prompt"):
                yield {"type": "prompt", "phase": "tool", "model": MODEL_FLASH,
                       "prompt": tr["_llm_prompt"], "label": f"工具: {step.get('tool', '?')}"}
            exec_results.append(step)
        llm_tool_count = sum(1 for r in exec_results if r.get("tool_result", {}).get("_llm_driven", False))
        yield {"type": "phase", "phase": "execute", "status": "done",
               "data": {"all_completed": True, "llm_driven_tools": llm_tool_count,
               "total_tools": len(exec_results), "executor": "parallel"}}

        # ====== Phase 6: 报告生成 (image直接输出URL跳过LLM) ======
        if detected_mode == "image":
            # 从执行结果中提取图片URL
            img_url = None
            for r in exec_results:
                tr = r.get("tool_result", {})
                if tr.get("url"):
                    img_url = tr["url"]
                    break
            if img_url:
                yield {"type": "image_result", "url": img_url,
                       "prompt": exec_results[0].get("tool_result", {}).get("prompt", "") if exec_results else ""}
            else:
                yield {"type": "error", "message": "图片生成失败"}
            self._update_memory(session_id, user_input, intent, f"[图片生成]{img_url}")
            self.tracer.finish(trace_id, success=bool(img_url))
            yield {"type": "summary", "data": get_metrics()}
            yield {"type": "done"}
            return

        # ====== Phase 6: 报告生成 (deepseek-chat, 低延迟)
        # 注入同类目历史分析参考
        category = intent.get("goal", {}).get("品类", "") or intent.get("entities", {}).get("category", "")
        related_history = self.memory.find_related_analyses(session_id, category,
                                                             intent.get("intent_type", ""))
        history_context = ""
        if related_history:
            lines = []
            for h in related_history:
                ts = time.strftime("%m-%d", time.localtime(h.get("timestamp", 0)))
                lines.append(f"- [{ts}] {h.get('query', '')[:40]}：{h.get('key_findings', '')[:120]}")
            history_context = "\n\n【历史分析参考】\n您此前对相关主题做过分析：\n" + "\n".join(lines) + "\n\n请参考以上历史结论，补充趋势变化和新发现。"
        yield {"type": "phase", "phase": "report", "status": "running", "model": MODEL_CHAT}
        p_report = self.report_builder.build_prompt(intent, detected_mode, exec_results, session_id)
        p_report += history_context
        yield {"type": "prompt", "phase": "report", "model": MODEL_CHAT, "prompt": p_report, "label": "Phase 6: 报告生成"}
        report = await self.report_builder.generate(intent, detected_mode, exec_results, session_id, prompt=p_report)
        yield {"type": "phase", "phase": "report", "status": "done", "data": {"generated": True, "length": len(report)}}

        # ====== Phase 7: 反思修正 (CostRouter控制) ======
        if self.router.should_include_reflection(complexity):
            TARGET_SCORE = 7
            MAX_RETRIES = self.router.get_max_retries(complexity)

            yield {"type": "phase", "phase": "reflect", "status": "running", "model": MODEL_PRO}
            p_reflect1 = self.reflection_engine.build_prompt(intent, report)
            yield {"type": "prompt", "phase": "reflect", "model": MODEL_CHAT, "prompt": p_reflect1, "label": "Phase 7: 初版质量审查"}
            reflection_v1 = await self.reflection_engine.evaluate(intent, report, prompt=p_reflect1)
            yield {"type": "phase", "phase": "reflect", "status": "done", "data": reflection_v1}

            report_versions = [report]
            retry_history = [reflection_v1]

            for attempt in range(1, MAX_RETRIES + 1):
                last_reflection = retry_history[-1]
                overall = last_reflection.get("scores", {}).get("overall", 0)
                if overall >= TARGET_SCORE:
                    break

                scores = last_reflection.get("scores", {})
                dc, ga, ac = scores.get("data_consistency", 5), scores.get("goal_alignment", 5), scores.get("actionability", 5)

                fixes = []
                if dc < TARGET_SCORE:
                    fixes.append(f"【数据一致性 {dc}/10→目标≥{TARGET_SCORE}】每个结论必须引用搜索数据原文片段作为证据。标注每条数据的来源(博查/Tavily)。统计数据用具体数字而非模糊描述。不确定的数据标注置信度(高/中/低)。")
                if ga < TARGET_SCORE:
                    fixes.append(f"【目标对齐 {ga}/10→目标≥{TARGET_SCORE}】逐条检查用户需求的每个要点是否被完整回答。遗漏的需求点必须补充。偏离主题的内容删除。")
                if ac < TARGET_SCORE:
                    fixes.append(f"【可落地性 {ac}/10→目标≥{TARGET_SCORE}】每个建议必须包含：具体¥价格/时间窗口/执行步骤/预期效果。'建议优化定价'不合格，'引流款定¥199、利润款定¥359、6月1日前上架'合格。")

                label = f"第{attempt}次重试"
                yield {"type": "phase", "phase": "reflect_retry", "status": "running",
                       "model": MODEL_PRO, "data": {"attempt": attempt, "label": label,
                       "score_before": overall, "target": TARGET_SCORE, "fixes": fixes}}

                instructions = f"⚠️ 质量不达标(当前{overall}/10，目标≥{TARGET_SCORE}/10)。必须逐条修复：\n" + "\n".join(fixes)
                instructions += f"\n\n这是第{attempt}次修正。如果仍然不达标将再次重试。请认真对待每一条修复指令。"

                p_retry_rpt = self.report_builder.build_prompt(intent, detected_mode, exec_results, session_id, instructions)
                yield {"type": "prompt", "phase": "retry_report", "model": MODEL_CHAT, "prompt": p_retry_rpt, "label": f"Phase 7b: 第{attempt}次修正报告"}
                retry_report = await self.report_builder.generate(
                    intent, detected_mode, exec_results, session_id,
                    improvement_instructions=instructions, max_tokens=4096, prompt=p_retry_rpt
                )
                report_versions.append(retry_report)

                yield {"type": "phase", "phase": "reflect_v2", "status": "running", "model": MODEL_PRO,
                       "data": {"label": f"第{attempt}次重试审查"}}
                p_reflect2 = self.reflection_engine.build_prompt(intent, retry_report)
                yield {"type": "prompt", "phase": "retry_reflect", "model": MODEL_CHAT, "prompt": p_reflect2, "label": f"Phase 7b: 第{attempt}次修正审查"}
                attempt_reflection = await self.reflection_engine.evaluate(intent, retry_report, prompt=p_reflect2)
                retry_history.append(attempt_reflection)
                new_score = attempt_reflection.get("scores", {}).get("overall", 0)
                yield {"type": "phase", "phase": "reflect_v2", "status": "done",
                       "data": {**attempt_reflection, "label": f"第{attempt}次重试审查",
                       "score_before": overall, "score_after": new_score, "attempt": attempt}}

            # 选择最高分版本
            best_idx = 0
            best_score = retry_history[0].get("scores", {}).get("overall", 0)
            for i, r in enumerate(retry_history):
                s = r.get("scores", {}).get("overall", 0)
                if s > best_score:
                    best_score = s
                    best_idx = i
            report = report_versions[best_idx]
            final_reflection = retry_history[best_idx]
            final_score = final_reflection.get("scores", {}).get("overall", 0)
            retried = len(retry_history) > 1

            yield {"type": "phase", "phase": "reflect_retry", "status": "done",
                   "data": {"retries": len(retry_history) - 1,
                   "final_score": best_score, "target": TARGET_SCORE,
                   "passed": best_score >= TARGET_SCORE,
                   "selected_version": best_idx,
                   "score_trail": [r.get("scores", {}).get("overall", "?") for r in retry_history]}}

            active_reflection = final_reflection
        else:
            yield {"type": "phase", "phase": "reflect", "status": "done",
                   "data": {"skipped": True, "reason": f"复杂度{self.router.complexity_label(complexity)}，跳过反思"}}

        self._update_memory(session_id, user_input, intent, report)
        await self.memory.flush()
        # 滑动窗口溢出时异步压缩（不阻塞主流程）
        asyncio.create_task(self.memory.compress_if_needed(
            session_id, lambda p: chat(p, model=MODEL_FLASH, max_tokens=200)))
        self.tracer.finish(trace_id, success=True)

        # 质量审查结果作为独立事件发送
        if 'active_reflection' in dir() and active_reflection:
            yield {"type": "quality_review", "data": {
                "passed": active_reflection.get("passed", True),
                "scores": active_reflection.get("scores", {}),
                "verdict": active_reflection.get("verdict", ""),
                "warnings": active_reflection.get("warnings", []),
                "retried": len(retry_history) > 1 if 'retry_history' in dir() else False,
                "shortfall": final_score < TARGET_SCORE if 'final_score' in dir() else False
            }}

        yield {"type": "result", "content": report}
        # 同类目历史对比事件
        if related_history:
            current_summary = ""
            try:
                import re
                m = re.search(r'"title"\s*:\s*"([^"]+)"', report)
                if m:
                    current_summary = m.group(1)[:100]
            except Exception:
                pass
            previous = []
            for h in related_history:
                ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(h.get("timestamp", 0)))
                previous.append({
                    "title": h.get("query", "")[:80],
                    "summary": h.get("key_findings", "")[:200],
                    "timestamp": ts,
                    "intent": h.get("intent", ""),
                })
            yield {"type": "history_comparison", "data": {
                "current": {"title": current_summary, "intent": intent.get("intent_type", "")},
                "previous": previous,
            }}
        # 写入缓存（24h，文件持久化）
        if len(report) > 100:
            self._report_cache[cache_key] = (time.time(), report)
            self._save_cache()
        yield {"type": "summary", "data": get_metrics()}
        yield {"type": "done"}

    # ====== 工具映射 + 执行
    def _map_tools(self, dag):
        tool_names = [t["name"] for t in AVAILABLE_TOOLS]
        mappings = []
        for t in dag.get("tasks", []):
            tool = t["tool"] if t["tool"] in tool_names else "web_search"
            desc = t.get("desc", "")
            if not desc:
                # 为每个工具生成有意义的默认描述
                label = next((at["description"] for at in AVAILABLE_TOOLS if at["name"] == tool), tool)
                desc = f"{label} ({t['id']})"
            mappings.append({
                "task_id": t["id"], "tool": tool, "desc": desc,
                "deps": t.get("deps", []), "parallel_group": t.get("parallel_group", 0)
            })
        return {"mappings": mappings, "total": len(mappings)}

    def _update_memory(self, session_id, user_input, intent, report):
        self.memory.append_conversation(session_id, "user", user_input)
        self.memory.append_conversation(session_id, "assistant", report[:800])
        self.memory.update_working_memory(session_id, "last_intent", intent.get("intent_type"))
        self.memory.add_knowledge(f"查询:{user_input[:80]}", [intent.get("intent_type", "")])

        # v2: 记录分析到工作记忆 + 维护多轮对话链
        goal = intent.get("goal", {})
        params = {"品类": goal.get("品类"), "风格": goal.get("风格"), "时间": goal.get("时间范围")}
        summary = report[:200].replace("<", " ").replace(">", " ").strip()
        self.memory.record_analysis(session_id, user_input, intent, summary, params)
        self.memory.append_session_chain(session_id, user_input, summary)

    def _load_cache(self) -> dict:
        """从文件加载报告缓存"""
        try:
            cf = DATA_DIR / "report_cache.json"
            if cf.exists():
                return json.loads(cf.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_cache(self):
        """持久化报告缓存到文件"""
        try:
            import json
            cf = DATA_DIR / "report_cache.json"
            cf.write_text(json.dumps(self._report_cache, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass


