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

        # ====== Phase 0: 多轮场景检测 + 查询增强 ======
        last_intent = self.memory.get_working_memory(session_id).get("last_intent", "")
        scenario = self.conversation.detect_scenario(user_input, last_intent)
        is_followup = self.conversation.is_followup(user_input)
        if scenario != Scenario.NEW_QUERY:
            wm = self.memory.get_working_context(session_id)
            enhanced_query = self.conversation.augment_query(user_input, scenario, wm)
            yield {"type": "phase", "phase": "conversation", "status": "done",
                   "data": {"scenario": scenario.name, "is_followup": is_followup,
                   "enhanced": enhanced_query != user_input}}
            user_input = enhanced_query

        # ====== Phase 1: LLM意图识别 + 工作记忆更新 ======
        yield {"type": "phase", "phase": "intent", "status": "running", "model": MODEL_FLASH}
        p_intent = self.intent_router.build_prompt(user_input, mode, session_id)
        yield {"type": "prompt", "phase": "intent", "model": MODEL_FLASH, "prompt": p_intent, "label": "Phase 1: 意图识别"}
        intent = await self.intent_router.classify(user_input, mode, session_id, prompt=p_intent)
        detected_mode = self.intent_router.route(intent)
        yield {"type": "phase", "phase": "intent", "status": "done",
               "data": {"intent": intent, "auto_routed": detected_mode}}

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

        # ====== 缓存检查 (24h相同query命中) ======
        cache_key = f"{user_input}|{mode or 'auto'}"
        if cache_key in self._report_cache:
            cached_time, cached_report = self._report_cache[cache_key]
            if time.time() - cached_time < 86400:  # 24h内有效
                yield {"type": "cache_hit", "data": {"cached": True, "age_hours": round((time.time()-cached_time)/3600, 1)}}
                yield {"type": "result", "content": cached_report}
                self.tracer.finish(trace_id, success=True)
                yield {"type": "summary", "data": get_metrics()}
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
            p_decompose = self._build_decompose_prompt(intent, detected_mode)
            yield {"type": "prompt", "phase": "decompose", "model": MODEL_PRO, "prompt": p_decompose, "label": "Phase 3: DAG任务拆解"}
            dag = await self._llm_decompose(intent, detected_mode, prompt=p_decompose)
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
        yield {"type": "phase", "phase": "report", "status": "running", "model": MODEL_CHAT}
        p_report = self.report_builder.build_prompt(intent, detected_mode, exec_results, session_id)
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
        # 写入缓存（24h，文件持久化）
        if len(report) > 100:
            self._report_cache[cache_key] = (time.time(), report)
            self._save_cache()
        yield {"type": "summary", "data": get_metrics()}
        yield {"type": "done"}

    # ====== Phase 1: LLM意图识别 (flash, P4记忆注入) ======
    def _build_intent_prompt(self, user_input: str, mode: str, session_id: str) -> str:
        memory_context = self._build_memory_context(session_id)
        return f"""你是服饰电商意图识别专家。从用户输入提取结构化JSON。

{memory_context}
用户当前输入: "{user_input}"
模式提示: {mode}

意图判定规则:
- 文生图: 用户描述了一件衣服的款式/风格/面料/色彩等视觉特征，目的是生成图片（含"生成""画一张""设计图""图片"等词，或纯视觉描述无分析需求）
- 单品选品分析: 用户要分析市场数据、价格带、趋势（含"选品""分析""机会""报告"等词）
- 商品文案生成: 用户要写标题/文案/详情页
- 多品牌竞品对标: 含两个及以上品牌对比
- 品类趋势洞察: 泛泛的趋势/流行方向询问
- 定价策略分析: 含定价/价格策略
- 上新排期优化: 含上新/排期/日历

输出JSON含:
- intent_type: "单品选品分析"|"多品牌竞品对标"|"品类趋势洞察"|"商品文案生成"|"定价策略分析"|"上新排期优化"|"文生图"
- confidence: 0-1
- entities: {{subject(品类/款式), category(类目), style(风格), time(时间), brands(品牌列表), platforms(平台列表)}}
- goal: {{任务类型, 分析对象, 品类, 风格, 时间范围, 目标平台, 竞品品牌, 核心关注点}}
- missing_info: [缺口] — 列举需要用户补充的信息
- context_note: "如从历史对话中有补充上下文，简述"

只输出JSON。"""

    async def _llm_intent(self, user_input: str, mode: str, session_id: str, prompt: str = None) -> dict:
        if prompt is None:
            prompt = self._build_intent_prompt(user_input, mode, session_id)
        raw = await chat(prompt, model=MODEL_FLASH, max_tokens=800)
        result = extract_json(raw)

        if not result or "intent_type" not in result:
            result = self._fallback_intent(user_input, mode)

        # Normalize intent_type: LLM sometimes returns English mode keys
        result = self._normalize_intent(result)

        return result

    def _normalize_intent(self, intent: dict) -> dict:
        """标准化意图类型：英文→中文映射"""
        en_to_cn = {
            "selection": "单品选品分析",
            "competitive": "多品牌竞品对标",
            "trend": "品类趋势洞察",
            "copy": "商品文案生成",
            "pricing": "定价策略分析",
            "launch": "上新排期优化",
        }
        it = intent.get("intent_type", "")
        if it in en_to_cn:
            intent["intent_type"] = en_to_cn[it]
        return intent

    def _build_memory_context(self, session_id: str) -> str:
        """P4: 构建记忆上下文"""
        conv = self.memory.get_conversation(session_id)
        if not conv or len(conv) <= 2:  # 只有初始欢迎消息，无有效历史
            return ""

        # 取最近3轮对话
        recent = conv[-6:]  # 3 user + 3 assistant
        lines = ["## 历史对话上下文"]
        for msg in recent:
            role_label = "用户" if msg["role"] == "user" else "助手"
            content = msg.get("content", "")[:200]
            lines.append(f"{role_label}: {content}")
        lines.append("")
        return "\n".join(lines)

    def _fallback_intent(self, text: str, mode: str) -> dict:
        type_map = {"selection": "单品选品分析", "competitive": "多品牌竞品对标",
                   "trend": "品类趋势洞察", "copy": "商品文案生成",
                   "pricing": "定价策略分析", "launch": "上新排期优化"}
        return {
            "intent_type": type_map.get(mode, "单品选品分析"),
            "confidence": 0.5,
            "entities": {"subject": "", "category": "女装", "style": "", "time": "2026夏季",
                        "brands": [], "platforms": ["淘宝", "天猫"]},
            "goal": {"任务类型": type_map.get(mode), "分析对象": "女装", "品类": "女装", "时间范围": "2026夏季"},
            "missing_info": ["需要更多上下文"],
            "_fallback": True
        }

    # ====== Phase 2: 前置校验 ======
    def _phase_precheck(self, intent: dict, user_input: str = "") -> dict:
        goal = intent.get("goal", {})
        llm_missing = intent.get("missing_info", [])

        hints = list(llm_missing)

        blocking_gaps = []
        analysis_object = goal.get("分析对象", "")
        # Pitfall 34 fix: 检查空字符串和占位符
        if not analysis_object or analysis_object in ("", "品类", "女装", "产品", "未指定"):
            blocking_gaps.append("请明确要分析的具体品类或款式（如：法式茶歇裙、通勤西装裤）")
        if intent.get("intent_type") == "多品牌竞品对标":
            brands = goal.get("竞品品牌", [])
            if not brands or not isinstance(brands, list) or len(brands) == 0:
                # 也检查是否以字符串形式传入
                if isinstance(brands, str) and brands not in ("", "未指定"):
                    pass  # 单个品牌名也接受
                else:
                    blocking_gaps.append("请指定要对标的品牌（至少1个）")

        if intent.get("intent_type") == "文生图":
            prompt_text = goal.get("核心关注点", "") or user_input
            if len(prompt_text) < 15:
                blocking_gaps.append("请提供更详细的图片描述（至少15字，含主体/风格/构图要素）")
            if not any(kw in prompt_text for kw in ["风格", "画质", "色彩", "光影", "构图", "氛围", "写实", "插画", "摄影", "3D", "动漫"]):
                hints.append("建议补充：风格偏好、色彩、光影氛围、画质要求（2K/4K）。默认生成为真实服装摄影图")

        return {
            "checks": {
                "info_completeness": {
                    "passed": len(blocking_gaps) == 0,
                    "gaps": blocking_gaps,
                    "hints": hints
                },
                "permission": {"passed": True, "gaps": []},
                "compliance": {"passed": True, "gaps": []},
                "dependency": {"passed": True, "gaps": []},
            },
            "confidence_matrix": {
                "依赖置信度": 0.90 if len(blocking_gaps) == 0 else 0.70,
                "可执行性": 0.92,
                "综合判定": "直接自动执行" if len(blocking_gaps) == 0 else "需用户补充信息"
            }
        }

    def _build_clarify_message(self, intent: dict, gaps: list) -> str:
        lines = ["📋 在开始分析之前，需要确认以下信息：", ""]
        for i, gap in enumerate(gaps, 1):
            lines.append(f"{i}. {gap}")
        lines.append("")
        lines.append("请补充以上信息，我会生成更精准的分析报告。")
        return "\n".join(lines)

    # ====== Phase 3: DAG拆解 (pro, P2差异化) ======
    def _build_decompose_prompt(self, intent: dict, detected_mode: str) -> str:
        goal = intent.get("goal", {})
        intent_type = intent.get("intent_type", "分析")
        tools_list = ", ".join([t["name"] for t in AVAILABLE_TOOLS])
        return f"""你是任务规划专家。根据用户意图和可用工具，自主设计最优DAG任务流。

意图类型: {intent_type}
用户目标: {json.dumps(goal, ensure_ascii=False)[:500]}

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

输出JSON:
{{"tasks":[{{"id":"T1","desc":"任务描述(简短)","tool":"工具名","deps":[],"parallel_group":0}}],
 "dag_structure":"结构描述",
 "parallel_groups":[["T2","T3"]],
 "rationale":"为什么这样设计DAG"}}

每个任务绑定一个工具, 无依赖可并行, 3-6个任务。可参考模板但要根据实际目标调整。
只输出JSON。"""

    async def _llm_decompose(self, intent: dict, detected_mode: str, prompt: str = None) -> dict:
        if prompt is None:
            prompt = self._build_decompose_prompt(intent, detected_mode)
        template = self.dag_loader.load(detected_mode) or self.dag_loader.load("selection")
        raw = await chat(prompt, model=MODEL_PRO, max_tokens=1200)
        result = extract_json(raw)

        if not result or "tasks" not in result:
            # fallback: 使用该意图的默认模板
            return {
                "tasks": template["tasks"],
                "dag_structure": template["dag_structure"],
                "parallel_groups": [["T2", "T3", "T4"]],
                "_fallback": True,
            }

        return result

    # ====== Phase 4-5: 工具映射 + 执行 (P0加持) ======
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

    def _execute(self, mappings):
        """执行任务 — 搜索结果管道传递给下游LLM工具"""
        task_map = {m["task_id"]: m for m in mappings.get("mappings", [])}
        search_pool = {}  # 所有搜索结果池，下游工具共享

        # 按依赖层级排序
        all_mappings = mappings.get("mappings", [])
        executed = set()

        def _deps_satisfied(deps, executed_set):
            return all(d in executed_set for d in deps)

        # 迭代执行，直到全部完成
        remaining = list(all_mappings)
        while remaining:
            ready = [m for m in remaining if _deps_satisfied(m.get("deps", []), executed)]
            if not ready:
                break  # 死锁保护

            for m in ready:
                # 汇聚上游数据
                upstream_data = {}
                for dep in m.get("deps", []):
                    if dep in search_pool:
                        upstream_data.update(search_pool[dep])

                params = {"query": m.get("desc", "")}
                if upstream_data:
                    params["raw_data"] = upstream_data

                tr = execute_tool_sync(m["tool"], params)
                result = {
                    "task_id": m["task_id"], "tool": m["tool"],
                    "state_before": "PENDING", "state_after": "COMPLETED",
                    "tool_result": tr
                }

                # 存储结果供下游使用
                search_pool[m["task_id"]] = tr

                executed.add(m["task_id"])
                remaining.remove(m)
                yield result

    # ====== 意图路由 ======
    def _route_by_intent(self, intent: dict) -> str:
        it = intent.get("intent_type", "")
        route_map = {
            "单品选品分析": "selection",
            "多品牌竞品对标": "competitive",
            "品类趋势洞察": "trend",
            "商品文案生成": "copy",
            "定价策略分析": "pricing",
            "上新排期优化": "launch",
            "文生图": "image",
            }
        for key, val in route_map.items():
            if key in it:
                return val
        return "selection"

    # ====== Phase 6: LLM报告 (pro, P3 + P4记忆注入) ======
    def _build_report_prompt(self, intent: dict, mode: str = "selection",
                             exec_results: list = None, session_id: str = "",
                             improvement_instructions: str = "") -> str:
        goal = intent.get("goal", {})
        intent_type = intent.get("intent_type", "分析")
        template = REPORT_TEMPLATES.get(mode, REPORT_TEMPLATES["selection"])
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
                    tool_insights.append(f"趋势: {td.get('direction','')} (热度{td.get('heat_score','?')}): {td.get('evidence','')[:100]}")
                for pb in tr.get("price_bands", [])[:3]:
                    tool_insights.append(f"价格带: {pb.get('label','')} ¥{pb.get('range_low','?')}-{pb.get('range_high','?')}")
                for comp in tr.get("competitors", [])[:3]:
                    tool_insights.append(f"竞品: {comp.get('brand','')} - {comp.get('positioning','')}")
        data_context = ""
        if search_snippets:
            data_context += "\n真实搜索数据:\n" + "\n".join(f"- {s}" for s in search_snippets[:5])
        if tool_insights:
            data_context += "\n\nLLM工具分析结果:\n" + "\n".join(f"- {s}" for s in tool_insights[:8])
        memory_note = self._build_report_memory_context(session_id, intent)
        return f"""你是服饰电商资深分析师和前端设计师。{template}

任务类型: {intent_type}
需求详情: {json.dumps(goal, ensure_ascii=False, indent=2)[:600]}
{memory_note}{data_context}
{improvement_instructions}

⚠️ 关键规范:
- 只输出纯内容HTML，使用规定的CSS class（rc-*），不生成<style>/<head>/<body>标签
- 所有数值数据必须用可视化组件呈现，不要只用文字描述
- rc-bar-chart柱状图：每个rc-bar-row含rc-bar-label+rc-bar-track>rc-bar-fill.c1/c2/c3(width用百分比)
- rc-metrics：用rc-metric卡片展示关键数字，.val放数值.lbl放说明
- rc-compare对比卡片：左右两栏，brand-a用品牌A数据，brand-b用品牌B数据
- rc-table表格：用thead+tbody+tr+th+td结构
- rc-swot：品牌A的SWOT用 rc-swot-wrap.brand-a，品牌B用 rc-swot-wrap.brand-b。rc-swot-title 显示品牌标签(.brand-tag.a/.brand-tag.b)，rc-swot 四宫格。每个 rc-swot-cell(.s/.w/.o/.t) 含 .cell-head（图标emoji+标题文字）和 .cell-body（ul>li）。两个品牌的SWOT矩阵结构相同、颜色不同。
- rc-insight：.tip绿色(建议)/.warn橙色(注意)/.danger红色(风险)，每框含<strong>标题
- rc-section-title：大分区标题，可加.gold/.sage变体色
- 报告底部加<div class="rc-footer-note">含数据来源和生成时间

专业、数据驱动、可落地。如数据不足，明确标注置信度。不要截断内容，完整展开所有分析。"""

    async def _llm_report(self, intent: dict, mode: str = "selection",
                          exec_results: list = None, session_id: str = "",
                          improvement_instructions: str = "", max_tokens: int = 3072,
                          prompt: str = None) -> str:
        if prompt is None:
            prompt = self._build_report_prompt(intent, mode, exec_results, session_id, improvement_instructions)
        raw = await chat(prompt, model=MODEL_CHAT, max_tokens=max_tokens)
        return _clean(raw)

    def _build_report_memory_context(self, session_id: str, intent: dict) -> str:
        """P4: 为报告生成构建记忆上下文（用户偏好+历史分析）"""
        working = self.memory.get_working_memory(session_id)
        conv = self.memory.get_conversation(session_id)

        notes = []

        # 历史分析意图
        last_intent = working.get("last_intent")
        if last_intent and last_intent != intent.get("intent_type"):
            notes.append(f"用户上轮分析: {last_intent}")

        # 历史品类偏好（从最近3轮对话中提取）
        recent_subjects = []
        for msg in conv[-8:]:
            if msg["role"] == "user":
                # 简单提取品类关键词
                content = msg.get("content", "")
                for kw in ["连衣裙", "茶歇裙", "衬衫", "西装", "裤", "外套", "T恤", "半裙", "风衣"]:
                    if kw in content and kw not in recent_subjects:
                        recent_subjects.append(kw)
        if recent_subjects:
            notes.append(f"用户历史关注品类: {', '.join(recent_subjects[-3:])}")

        if notes:
            return "\n## 用户上下文\n" + "\n".join(f"- {n}" for n in notes) + "\n"
        return ""

    # ====== Phase 7: 反思修正 (pro, P1 新增) ======
    def _build_reflect_prompt(self, intent: dict, report: str) -> str:
        goal = intent.get("goal", {})
        report_sample = report[:4000] if report else ""
        return f"""你是AI Agent质检专家。反思以下分析报告的质量。

原始需求: {json.dumps(goal, ensure_ascii=False)[:400]}
报告摘要 (前2000字符): {report_sample}

从三个维度评分（每项0-10）并输出JSON:

{{
  "scores": {{
    "data_consistency": 分数,    // 报告结论是否与可用数据一致？有无编造数据？
    "goal_alignment": 分数,      // 是否回答了用户的核心问题？有无跑偏？
    "actionability": 分数        // 结论是否可落地？有无具体建议？
  }},
  "overall": 总分平均,
  "passed": true/false,          // overall>=6 为通过
  "issues": ["问题1"],          // 具体问题列表
  "warnings": ["警告1"],        // 潜在风险但不严重
  "verdict": "一句话总结"
}}

只输出JSON。严格评分，不要放水。"""

    async def _llm_reflect(self, intent: dict, mode: str, exec_results: list, report: str,
                           prompt: str = None) -> dict:
        """反思报告质量：数据一致性 + Goal对齐 + 可落地性"""
        if prompt is None:
            prompt = self._build_reflect_prompt(intent, report)
        raw = await chat(prompt, model=MODEL_CHAT, max_tokens=800)
        result = extract_json(raw)

        if not result or "scores" not in result:
            return {"passed": True, "scores": {"overall": 7}, "warnings": ["反思LLM返回异常，跳过校验"], "_fallback": True}

        # 用Python计算overall，而非依赖LLM（LLM经常算错）
        scores = result.get("scores", {})
        dims = [scores.get(k, 5) for k in ("data_consistency", "goal_alignment", "actionability")]
        scores["overall"] = round(sum(dims) / len(dims), 1)
        result["passed"] = scores["overall"] >= 6
        result["scores"] = scores

        return result

    def _annotate_report(self, reflection: dict, report: str, intent: dict, retried: bool = False) -> str:
        """反思不通过时，在报告末尾追加质量标注"""
        report = report.rstrip()
        scores = reflection.get("scores", {})
        verdict = reflection.get("verdict", "")
        overall = scores.get("overall", 0)

        retry_note = ""
        if retried:
            retry_note = '<p style="margin:4px 0;color:#2a7a4a;font-weight:500">🔄 本报告已根据反思结果自动重试优化（4096 tokens），以下为修正后评分</p>'

        annotation = f"""
<div style="margin-top:20px;padding:14px 18px;background:#fef9f0;border-left:3px solid #e0a060;border-radius:6px;font-size:13px">
  <h4 style="margin:0 0 8px;color:#b07030">📋 质量审查</h4>
  {retry_note}
  <p style="margin:4px 0"><strong>综合评分:</strong> {overall}/10 — {verdict}</p>
  <p style="margin:4px 0"><strong>数据一致性:</strong> {scores.get('data_consistency','?')}/10 | <strong>目标对齐:</strong> {scores.get('goal_alignment','?')}/10 | <strong>可落地性:</strong> {scores.get('actionability','?')}/10</p>
  <p style="margin:4px 0;color:#c06030;font-size:12px">⚠️ 以上分析存在质量风险，建议结合人工判断使用。</p>
</div>"""

        return report + annotation

    def _annotate_warnings(self, reflection: dict, report: str) -> str:
        """有警告时追加提示"""
        report = report.rstrip()
        warnings = reflection.get("warnings", [])
        if not warnings:
            return report

        warn_text = "<br>".join(f"· {w}" for w in warnings[:3])
        scores = reflection.get("scores", {})

        annotation = f"""
<div style="margin-top:20px;padding:12px 16px;background:#f8faf8;border-left:3px solid #8b9d83;border-radius:6px;font-size:12px;color:#6b7d63">
  <strong>💡 质量提示</strong> (评分: {scores.get('overall','?')}/10)<br>
  {warn_text}
</div>"""

        return report + annotation

    def _annotate_passed(self, reflection: dict, report: str, retried: bool = False) -> str:
        """反思通过时追加绿色评分摘要"""
        report = report.rstrip()
        scores = reflection.get("scores", {})
        overall = scores.get("overall", 0)
        verdict = reflection.get("verdict", "")

        retry_note = ""
        if retried:
            retry_note = '<p style="margin:4px 0;color:#2a7a4a;font-size:12px">🔄 本报告经自动修正后达标</p>'

        annotation = f"""
<div style="margin-top:20px;padding:14px 18px;background:#f0f7f0;border-left:3px solid #8b9d83;border-radius:6px;font-size:13px">
  <h4 style="margin:0 0 8px;color:#5a7d5a">✅ 质量审查通过</h4>
  {retry_note}
  <p style="margin:4px 0"><strong>综合评分:</strong> {overall}/10 — {verdict}</p>
  <p style="margin:4px 0"><strong>数据一致性:</strong> {scores.get('data_consistency','?')}/10 | <strong>目标对齐:</strong> {scores.get('goal_alignment','?')}/10 | <strong>可落地性:</strong> {scores.get('actionability','?')}/10</p>
  <p style="margin:4px 0;color:#5a7d5a;font-size:12px">✅ 报告质量达标，可直接参考使用。</p>
</div>"""

        return report + annotation

    # ====== 记忆更新 ======
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

    def _build_image_optimize_prompt(self, user_prompt: str) -> str:
        is_design_sketch = any(kw in user_prompt for kw in ["设计图", "设计稿", "线稿", "效果图", "款式图", "版型图", "草图", "手绘"])
        wants_model = any(kw in user_prompt for kw in ["模特", "上身", "穿着", "真人", "试穿", "走秀"])
        if is_design_sketch:
            style_guide = "这是一张服装设计师专业线稿/效果图，手绘风格或电脑绘图，展示服装的正面和背面版型，标注面料和设计细节"
        elif wants_model:
            style_guide = "这是一张真实时尚摄影照片，真人模特穿着展示，专业影棚灯光，高清商业摄影质感"
        else:
            style_guide = "这是一张真实服装产品摄影图，衣服挂在衣架上或平铺展示，纯色干净背景，高清商业摄影质感，电商白底图风格，展示服装全貌"
        return f"""你是服装摄影/设计prompt优化专家。将用户的描述改写为适合AI生图的prompt。

风格要求: {style_guide}

规则:
1. 开头必须明确这是一张什么类型的图片（真实摄影/设计稿/平铺图）
2. 如果是真实摄影，强调「高清摄影」「商业摄影」「真实质感」「写实」，避免插画/卡通/3D渲染等词汇
3. 面料质感作为辅助描述，不要变成面料特写
4. 描述整件衣服的全貌，展示服装整体廓形
5. 保留用户指定的风格、色彩、光影要求
6. 豆包Seedream偏好：主体明确、光影真实、质感细腻

用户描述: {user_prompt}

只输出优化后的prompt文本，不要加任何解释。"""

    async def _optimize_image_prompt(self, user_prompt: str, prompt: str = None) -> str:
        """用LLM优化文生图prompt"""
        if prompt is None:
            prompt = self._build_image_optimize_prompt(user_prompt)
        try:
            raw = await chat(prompt, model=MODEL_FLASH, max_tokens=400)
            return raw.strip() or user_prompt
        except Exception:
            return user_prompt


    # ====== 报告缓存 ======

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


def _clean(text):
    """清理LLM输出: 去除废话前缀和代码块标记"""
    text = text.strip()

    # 1. 移除 ```html ... ``` 包裹
    if '```html' in text:
        start = text.find('```html')
        end = text.rfind('```')
        if start != -1 and end != -1 and end > start:
            text = text[start+7:end].strip()
    elif text.startswith('```'):
        lines = text.split('\n')
        text = '\n'.join(lines[1:-1] if lines and lines[-1].strip() == '```' else lines[1:])

    # 2. 移除代码块残留
    text = text.replace('```html', '').replace('```', '')

    # 3. 找到第一个 < 开头
    lt_pos = text.find('<')
    if lt_pos > 0:
        text = text[lt_pos:]

    # 4. 提取body内容（正则匹配HTML标签，避免误匹配CSS body {）
    text = re.sub(r'<!DOCTYPE\s+html[^>]*>', '', text, flags=re.IGNORECASE).strip()
    text = re.sub(r'^<html[^>]*>', '', text, flags=re.IGNORECASE).strip()
    text = re.sub(r'</html>\s*$', '', text, flags=re.IGNORECASE).strip()
    text = re.sub(r'<head[^>]*>.*?</head>', '', text, flags=re.IGNORECASE | re.DOTALL).strip()
    text = re.sub(r'<body[^>]*>', '', text, count=1, flags=re.IGNORECASE).strip()
    text = re.sub(r'</body>', '', text, flags=re.IGNORECASE).strip()

    return text.strip()
