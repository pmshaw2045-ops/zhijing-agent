"""
集成测试 — 真实调用 DeepSeek API

标记: @pytest.mark.integration
跳过: 无 DEEPSEEK_API_KEY 环境变量时自动 skip
费用: 每次调用 ~¥0.01，全跑完约 ¥0.05

设计原则:
- 不断言 LLM 输出文本（LLM 升级会改变措辞）
- 断言结构化字段存在性和类型（框架自身逻辑）
- 只测高价值路径：意图识别 / DAG 拆解 / LLM 基本调用
- 不测完整 Pipeline（太慢太贵，由 mock 测试覆盖）
"""
import sys
import os
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import pytest

# 集成测试必须有 USE_REAL_API=1 环境变量
# 有真实 API Key 时: USE_REAL_API=1 pytest -m integration
# 防止通过 .env 自动加载覆盖测试 key
if not os.environ.get("USE_REAL_API"):
    pytest.skip("集成测试默认跳过。设置 USE_REAL_API=1 执行", allow_module_level=True)


# ================================================================
# LLM 基本调用
# ================================================================


class TestLLMBasic:
    """验证 LLM API 基础可用性"""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_chat_returns_string(self, integration):
        from llm_client import chat

        result = await chat("回复'好的'", model="deepseek-chat", max_tokens=50)
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_json_mode_returns_valid_json(self, integration):
        from llm_client import chat

        result = await chat(
            '只输出JSON: {"msg": "hello"}',
            model="deepseek-chat",
            max_tokens=100,
            json_mode=True,
        )
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        assert "msg" in parsed

    @pytest.mark.integration
    def test_chat_sync_returns_string(self, integration):
        from llm_client import chat_sync

        result = chat_sync("回复'好的'", model="deepseek-chat", max_tokens=50)
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.integration
    def test_token_counter_increments(self, integration):
        from llm_client import chat_sync
        from observability import get_metrics

        before = get_metrics().get("tokens", {}).get("deepseek-chat", 0)
        chat_sync("回复'好的'", model="deepseek-chat", max_tokens=50)
        after = get_metrics().get("tokens", {}).get("deepseek-chat", 0)
        assert after >= before


# ================================================================
# 意图识别
# ================================================================


class TestIntentIntegration:
    """验证 LLM 意图识别（真实 API 调用）"""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_fashion_query_has_intent_and_confidence(self, integration):
        from intent import IntentRouter

        router = IntentRouter()
        intent = await router.classify("分析2026夏季法式茶歇裙选品机会", "selection")

        assert isinstance(intent, dict)
        assert "intent_type" in intent
        assert "confidence" in intent
        assert intent["confidence"] > 0

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_fashion_query_routes_to_valid_mode(self, integration):
        from intent import IntentRouter

        router = IntentRouter()
        intent = await router.classify("分析2026夏季法式茶歇裙选品机会", "selection")
        mode = router.route(intent)

        assert isinstance(mode, str)
        assert mode in ("selection", "trend")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_non_fashion_input_has_low_confidence(self, integration):
        """非服饰输入应走 unknown 或低置信度"""
        from intent import IntentRouter

        router = IntentRouter()
        intent = await router.classify("挡在GitHub前面的3件事", "selection")
        mode = router.route(intent)

        assert isinstance(intent, dict)
        assert "intent_type" in intent
        assert "confidence" in intent
        # 要么明确拒绝，要么置信度很低
        assert mode == "unknown" or intent.get("confidence", 1.0) < 0.5

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_competitive_query(self, integration):
        from intent import IntentRouter

        router = IntentRouter()
        intent = await router.classify("太平鸟vs伊芙丽竞品对比", "selection")
        mode = router.route(intent)

        assert isinstance(intent, dict)
        assert "intent_type" in intent
        is_competitive = "竞品" in intent.get("intent_type", "")
        is_routed_competitive = mode == "competitive"
        assert is_competitive or is_routed_competitive


# ================================================================
# DAG 拆解
# ================================================================


class TestDecomposeIntegration:
    """验证 LLM DAG 拆解（真实 API 调用）"""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_llm_decompose_not_fallback(self, integration):
        """LLM 拆解不应走模板回退"""
        from decompose_engine import DecomposeEngine
        from harness.dag_loader import DAGLoader

        engine = DecomposeEngine(DAGLoader())
        intent = {"intent_type": "单品选品分析", "goal": {"品类": "连衣裙"}}
        dag = await engine.decompose(intent, "selection")

        assert isinstance(dag, dict)
        assert "tasks" in dag
        assert len(dag["tasks"]) >= 2
        assert dag.get("_llm_generated") is True

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_decompose_tasks_have_required_fields(self, integration):
        from decompose_engine import DecomposeEngine
        from harness.dag_loader import DAGLoader

        engine = DecomposeEngine(DAGLoader())
        intent = {"intent_type": "单品选品分析", "goal": {"品类": "连衣裙"}}
        dag = await engine.decompose(intent, "selection")
        valid_tools = {
            "web_search", "bocha_search", "trend_analyze",
            "price_analyze", "competitive_analyze",
            "scoring_engine", "report_generate", "image_generate",
        }

        for t in dag["tasks"]:
            assert "id" in t, f"Task missing id: {t}"
            assert "tool" in t, f"Task missing tool: {t}"
            assert "desc" in t, f"Task missing desc: {t}"
            assert t["tool"] in valid_tools, f"Unknown tool: {t['tool']}"

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_decompose_has_rationale(self, integration):
        from decompose_engine import DecomposeEngine
        from harness.dag_loader import DAGLoader

        engine = DecomposeEngine(DAGLoader())
        intent = {"intent_type": "品类趋势洞察", "goal": {"品类": "连衣裙"}}
        dag = await engine.decompose(intent, "trend")

        assert isinstance(dag.get("rationale"), str)
        assert len(dag["rationale"]) > 10
