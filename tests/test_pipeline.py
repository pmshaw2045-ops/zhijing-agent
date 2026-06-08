"""Pipeline 集成测试 — mock LLM 调用，验证核心流程"""
import sys, json, pytest, asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))


@pytest.fixture
def mock_chat():
    """Mock chat() to return controlled responses"""
    responses = {}

    def set_response(trigger: str, response: str):
        responses[trigger] = response

    async def mock(prompt, model=None, max_tokens=None, json_mode=False):
        for trigger, response in responses.items():
            if trigger in prompt:
                return response
        return "{}"

    mock.set_response = set_response
    return mock


class TestDecomposeFlow:
    """DAG 拆解流程"""

    @pytest.mark.asyncio
    async def test_llm_decompose_with_params_format(self, mock_chat):
        """LLM输出 params.query 格式 → 标准化后 desc 应正确"""
        from decompose_engine import DecomposeEngine
        from harness.dag_loader import DAGLoader
        import decompose_engine as de_mod

        mock_chat.set_response("任务规划",
            '{"tasks":[{"id":"1","tool":"bocha_search","params":{"query":"搜索连衣裙趋势"}},'
            '{"id":"2","tool":"bocha_search","params":{"query":"搜索价格带"}},'
            '{"id":"3","tool":"report_generate","depends_on":["1","2"]}]}')

        with patch.object(de_mod, 'chat', mock_chat):
            engine = DecomposeEngine(DAGLoader())
            intent = {"intent_type": "品类趋势洞察", "goal": {"品类": "连衣裙"}}
            dag = await engine.decompose(intent, "trend")

        assert dag.get("_llm_generated") is True
        assert len(dag["tasks"]) == 3
        assert dag["tasks"][0]["desc"] == "搜索连衣裙趋势"
        assert dag["tasks"][0]["tool"] == "bocha_search"

    @pytest.mark.asyncio
    async def test_decompose_fallback_on_invalid_json(self, mock_chat):
        """LLM返回非法JSON → 回退模板"""
        from decompose_engine import DecomposeEngine
        from harness.dag_loader import DAGLoader
        import decompose_engine as de_mod

        mock_chat.set_response("任务规划", "这不是JSON{broken")

        with patch.object(de_mod, 'chat', mock_chat):
            engine = DecomposeEngine(DAGLoader())
            intent = {"intent_type": "品类趋势洞察", "goal": {"品类": "连衣裙"}}
            dag = await engine.decompose(intent, "trend")

        assert dag.get("_fallback") is True
        assert "tasks" in dag

    @pytest.mark.asyncio
    async def test_decompose_with_description_field(self, mock_chat):
        """LLM输出 description 字段 → 标准化后 desc 应正确"""
        from decompose_engine import DecomposeEngine
        from harness.dag_loader import DAGLoader
        import decompose_engine as de_mod

        mock_chat.set_response("任务规划",
            '{"tasks":[{"id":"1","tool":"bocha_search","description":"搜索热词"},'
            '{"id":"2","tool":"report_generate"}]}')

        with patch.object(de_mod, 'chat', mock_chat):
            engine = DecomposeEngine(DAGLoader())
            dag = await engine.decompose(intent={"intent_type": "商品文案生成", "goal": {}}, detected_mode="copy")

        assert dag["tasks"][0]["desc"] == "搜索热词"

    @pytest.mark.asyncio
    async def test_goal_to_text_conversion(self):
        """Goal dict → 自然语言"""
        from intent import goal_to_text

        result = goal_to_text({"品类": "连衣裙", "风格": "法式", "时间范围": "2026夏季"})
        assert "品类：连衣裙" in result
        assert "风格：法式" in result
        assert "{" not in result  # 不应含JSON


class TestPrecheckFlow:
    """前置校验流程"""

    def test_vague_input_blocked(self):
        """模糊输入 → 拦截"""
        from precheck import PrecheckEngine
        pe = PrecheckEngine()
        intent = {"intent_type": "单品选品分析", "entities": {"subject": None, "category": None},
                   "goal": {"品类": None}}
        result = pe.check(intent, "帮我看看现在卖什么好")
        assert result["checks"]["info_completeness"]["passed"] is False
        assert len(result["checks"]["info_completeness"]["gaps"]) >= 1

    def test_specific_input_passes(self):
        """具体输入 → 通过"""
        from precheck import PrecheckEngine
        pe = PrecheckEngine()
        intent = {"intent_type": "单品选品分析",
                   "entities": {"subject": "连衣裙", "category": "连衣裙"},
                   "goal": {"品类": "连衣裙"}}
        result = pe.check(intent, "连衣裙趋势")
        assert result["checks"]["info_completeness"]["passed"] is True

    def test_competitive_requires_brands(self):
        """竞品意图需要品牌"""
        from precheck import PrecheckEngine
        pe = PrecheckEngine()
        intent = {"intent_type": "多品牌竞品对标",
                   "entities": {"subject": "连衣裙", "category": "连衣裙"},
                   "goal": {"品类": "连衣裙", "竞品品牌": []}}
        result = pe.check(intent, "帮我做个竞品分析")
        assert result["checks"]["info_completeness"]["passed"] is False

    def test_clarify_message_format(self):
        """澄清消息格式正确"""
        from precheck import PrecheckEngine
        pe = PrecheckEngine()
        msg = pe.build_clarify({"gaps": ["请明确品类"], "hints": ["补充平台"]})
        assert "确认以下信息" in msg
        assert "请明确品类" in msg
