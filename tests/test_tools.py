"""tools.py 单元测试 — LLM驱动工具 + 搜索工具

测试策略：
- _build_search_context: 纯函数，各种输入边界
- _llm_extract: mock OpenAI 层验证 JSON 解析和 fallback
- _score_candidates: 空候选快速路径（无LLM调用）
- execute_tool_sync: 路由覆盖 + 参数传递验证

不测得：
- 真实网络搜索（_tavily_search_sync, _bocha_search_sync）→ 依赖真实API key
- _image_generate → 依赖ARK API
"""
import sys, json, pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# # sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))


# ============ Fixtures ============


@pytest.fixture
def mock_sync_openai():
    """Mock _sync_client.chat.completions.create — tools.py 使用 chat_sync，走同步客户端"""
    def _make_response(text: str):
        return MagicMock(choices=[MagicMock(message=MagicMock(content=text))])

    import backend.llm_client as llm_mod

    with patch.object(llm_mod._sync_client.chat.completions, 'create',
                      return_value=_make_response(json.dumps({
                          "trend_directions": [{"direction": "法式复古风", "heat_score": 85,
                                                "evidence": "搜索热度上升", "keywords": ["法式", "茶歇裙"]}],
                          "fabric_trends": ["蕾丝", "真丝"],
                          "style_trends": ["法式复古"],
                          "silhouette_trends": ["A字廓形"],
                          "summary": "法式茶歇裙搜索热度持续上升"
                      }))):
        yield


# ============ _build_search_context 测试 ============


class TestBuildSearchContext:
    """_build_search_context 纯函数测试"""

    def test_with_snippets(self):
        from backend.tools import _build_search_context
        raw_data = {
            "snippets": ["[标题A](url): 内容A", "[标题B](url): 内容B"],
        }
        result = _build_search_context(raw_data, "茶歇裙")
        assert "- [标题A]" in result
        assert "- [标题B]" in result

    def test_with_raw_results(self):
        from backend.tools import _build_search_context
        raw_data = {
            "raw_results": [{"content": "结果1内容"}, {"content": "结果2内容"}],
        }
        result = _build_search_context(raw_data, "茶歇裙")
        assert "结果1内容" in result
        assert "结果2内容" in result

    def test_with_summary_only(self):
        from backend.tools import _build_search_context
        raw_data = {"summary": "这是一个关于连衣裙的搜索摘要", "results_count": 5}
        result = _build_search_context(raw_data, "连衣裙")
        assert "连衣裙" in result
        assert len(result) <= 1500

    def test_empty_dict_returns_empty(self):
        """{} 是 falsy → 代码走 not raw_data 分支返回 ''"""
        from backend.tools import _build_search_context
        result = _build_search_context({}, "茶歇裙")
        assert result == ""

    def test_none_raw_data(self):
        from backend.tools import _build_search_context
        result = _build_search_context(None, "茶歇裙")
        assert result == ""

    def test_invalid_type(self):
        from backend.tools import _build_search_context
        result = _build_search_context("not a dict", "茶歇裙")
        assert result == ""


# ============ _llm_extract 测试 ============


class TestLlmExtract:
    """_llm_extract — mock OpenAI 层"""

    def test_successful_extraction(self, mock_sync_openai):
        from backend.tools import _llm_extract
        result = _llm_extract("分析: {query}\n数据: {search_text}",
                              {"snippets": ["测试数据"]}, "茶歇裙", "trend_analyze")
        assert result.get("_llm_driven") is True
        assert result.get("data_source") in ("search_engine", "llm_knowledge")

    def test_extraction_with_empty_search_context(self, mock_sync_openai):
        """无搜索结果时，llm_knowledge 作为数据源"""
        from backend.tools import _llm_extract
        result = _llm_extract("分析: {query}\n数据: {search_text}",
                              {}, "法式风", "trend_analyze")
        assert result.get("_llm_driven") is True
        assert result.get("data_source") == "llm_knowledge"

    def test_llm_returns_invalid_json(self):
        """LLM 返回非JSON → 走 fallback 路径"""
        from backend.tools import _llm_extract
        import backend.llm_client as llm_mod

        with patch.object(llm_mod._sync_client.chat.completions, 'create',
                          return_value=MagicMock(
                              choices=[MagicMock(message=MagicMock(content="这不是JSON"))])):
            result = _llm_extract("分析: {query}\n数据: {search_text}",
                                  {"snippets": ["测试"]}, "test", "trend_analyze")
        assert result.get("_llm_driven") is False
        assert result.get("error") == "LLM extraction failed"
        assert result.get("tool") == "trend_analyze"

    def test_llm_raises_exception(self):
        """LLM 调用抛异常 → fallback"""
        from backend.tools import _llm_extract
        import backend.llm_client as llm_mod

        with patch.object(llm_mod._sync_client.chat.completions, 'create',
                          side_effect=Exception("API timeout")):
            result = _llm_extract("分析: {query}\n数据: {search_text}",
                                  {"snippets": ["测试"]}, "test", "price_analyze")
        assert result.get("_llm_driven") is False
        assert result.get("tool") == "price_analyze"

    def test_prompt_format_with_special_chars(self):
        """prompt 含 {} 符号时 format 不应炸 — 但当前代码用 .format() 有潜在风险"""
        from backend.tools import _llm_extract
        import backend.llm_client as llm_mod

        with patch.object(llm_mod._sync_client.chat.completions, 'create',
                          return_value=MagicMock(
                              choices=[MagicMock(message=MagicMock(content='{"ok": true}'))])):
            # {} 在 query 中需要通过 prompt_template 传入
            # 这里测试 search_text 中包含 {} 是否会导致 format 炸
            result = _llm_extract("分析: {query}, 数据: {search_text}",
                                  {"summary": "这个{item}价格在{}范围"}, "测试", "test_tool")
            # 若 format 没炸，应正常返回
            assert result.get("_llm_driven") is True


# ============ _score_candidates 测试 ============


class TestScoreCandidates:
    """_score_candidates — 评分逻辑"""

    def test_empty_candidates_no_llm(self):
        """空候选 → 快速路径，不调用 LLM"""
        from backend.tools import _score_candidates
        import backend.llm_client as llm_mod
        original_sync = llm_mod._sync_client.chat.completions.create

        result = _score_candidates({"candidates": [], "criteria": []})
        # 验证没有调用 LLM
        assert result.get("scored") == 0
        assert result.get("_llm_driven") is False
        assert "无候选" in result.get("summary", "")

    def test_string_candidates(self):
        """candidates 是字符串 → 包装为列表"""
        import backend.llm_client as llm_mod
        from backend.tools import _score_candidates

        with patch.object(llm_mod._sync_client.chat.completions, 'create',
                          return_value=MagicMock(
                              choices=[MagicMock(message=MagicMock(
                                  content='{"scores":[{"candidate":"茶歇裙","total":85,"dimensions":{}}],"summary":"OK"}'))])):
            result = _score_candidates({"candidates": "茶歇裙", "criteria": []})
        assert result.get("_llm_driven") is True
        assert result.get("tool") == "scoring_engine"

    def test_default_criteria_when_empty(self):
        """空 criteria → 使用默认评分维度"""
        import backend.llm_client as llm_mod
        from backend.tools import _score_candidates

        with patch.object(llm_mod._sync_client.chat.completions, 'create') as mock_create:
            mock_create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(
                    content='{"scores":[],"summary":"OK"}'))])
            _score_candidates({"candidates": ["茶歇裙"], "criteria": []})
            # 验证 prompt 中包含默认维度
            call_kwargs = mock_create.call_args[1]
            prompt = call_kwargs.get("messages", [{}])[0].get("content", "")
            assert "市场热度" in prompt
            assert "利润空间" in prompt
            assert "竞争强度" in prompt


# ============ execute_tool_sync 路由测试 ============


class TestExecuteToolSync:
    """execute_tool_sync 路由分发"""

    def test_route_report_generate(self):
        from backend.tools import execute_tool_sync
        result = execute_tool_sync("report_generate", {})
        assert result.get("status") == "delegated_to_llm"

    def test_route_unknown_tool(self):
        from backend.tools import execute_tool_sync
        result = execute_tool_sync("nonexistent_tool", {})
        assert "error" in result
        assert "Unknown" in result["error"]

    def test_route_trend_analyze(self, mock_sync_openai):
        from backend.tools import execute_tool_sync
        result = execute_tool_sync("trend_analyze", {"query": "茶歇裙", "raw_data": {"snippets": ["数据"]}})
        assert result.get("tool") == "trend_analyze"
        assert result.get("_llm_driven") is True

    def test_route_price_analyze(self, mock_sync_openai):
        from backend.tools import execute_tool_sync
        result = execute_tool_sync("price_analyze", {"query": "连衣裙", "raw_data": {"snippets": ["价格数据"]}})
        assert result.get("tool") == "price_analyze"
        assert result.get("_llm_driven") is True

    def test_route_competitive_analyze(self, mock_sync_openai):
        from backend.tools import execute_tool_sync
        result = execute_tool_sync("competitive_analyze", {"query": "品牌A vs 品牌B", "raw_data": {"snippets": ["竞品数据"]}})
        assert result.get("tool") == "competitive_analyze"
        assert result.get("_llm_driven") is True

    def test_route_scoring_no_candidates(self):
        """空候选 → 路由到 _score_candidates 的快速路径"""
        from backend.tools import execute_tool_sync
        result = execute_tool_sync("scoring_engine", {"candidates": [], "criteria": []})
        assert result.get("tool") == "scoring_engine"
        assert result.get("scored") == 0


# ============ AVAILABLE_TOOLS 完整性测试 ============


class TestAvailableTools:
    """AVAILABLE_TOOLS 列表完整性"""

    def test_all_tools_have_required_fields(self):
        from backend.tools import AVAILABLE_TOOLS
        for t in AVAILABLE_TOOLS:
            assert "name" in t, f"Tool missing 'name': {t}"
            assert "description" in t, f"Tool {t['name']} missing 'description'"
            assert "parameters" in t, f"Tool {t['name']} missing 'parameters'"

    def test_tool_list_contains_expected_tools(self):
        from backend.tools import AVAILABLE_TOOLS
        names = [t["name"] for t in AVAILABLE_TOOLS]
        expected = ["web_search", "bocha_search", "trend_analyze", "price_analyze",
                     "competitive_analyze", "scoring_engine", "report_generate", "image_generate"]
        for name in expected:
            assert name in names, f"Missing tool: {name}"

    def test_tool_names_no_duplicates(self):
        from backend.tools import AVAILABLE_TOOLS
        names = [t["name"] for t in AVAILABLE_TOOLS]
        assert len(names) == len(set(names)), "Duplicate tool names found"
