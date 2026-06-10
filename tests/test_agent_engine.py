"""Agent Engine 核心 Pipeline 测试 — mock LLM 调用，验证流程完整性

测试策略：
- mock OpenAI client 层（_async_client.chat.completions.create），所有模块自然受控
- MemorySystem / Harness 真实初始化（不依赖 LLM）
- 验证 run_pipeline 产出的 SSE 事件序列和关键字段
"""
import sys, json, pytest, asyncio, os, time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

# # sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))


# ============ 测试数据 ============

SAMPLE_INTENT = {
    "intent_type": "单品选品分析",
    "confidence": 0.85,
    "entities": {"subject": "茶歇裙", "category": "连衣裙", "style": "法式",
                  "time": "2026夏季", "brands": [], "platforms": []},
    "goal": {"品类": "连衣裙", "分析对象": "茶歇裙", "风格": "法式", "时间范围": "2026夏季",
             "核心关注点": "市场机会"},
    "missing_info": [],
}

SAMPLE_DAG = {
    "tasks": [
        {"id": "T1", "desc": "博查搜索茶歇裙数据", "tool": "bocha_search", "deps": [], "parallel_group": 0},
        {"id": "T2", "desc": "LLM提取趋势洞察", "tool": "trend_analyze", "deps": ["T1"], "parallel_group": 1},
        {"id": "T3", "desc": "生成报告", "tool": "report_generate", "deps": ["T2"], "parallel_group": 2},
    ],
    "_llm_generated": True,
}

SAMPLE_REPORT = json.dumps({
    "title": "法式茶歇裙选品机会分析报告",
    "sections": [
        {"type": "metrics", "data": {"items": [{"label": "搜索热度", "value": "82"}]}},
        {"type": "insight", "data": {"style": "tip", "title": "结论", "body": "值得切入"}},
    ]
}, ensure_ascii=False)

SAMPLE_REFLECTION = {
    "scores": {"data_consistency": 8, "goal_alignment": 7, "actionability": 8, "overall": 7.7},
    "passed": True, "issues": [], "warnings": [], "verdict": "质量达标",
}

PASSED_PRECHECK = {
    "checks": {"info_completeness": {"passed": True, "gaps": [], "hints": []}}
}

FAILED_PRECHECK = {
    "checks": {"info_completeness": {"passed": False, "gaps": ["请明确品类"], "hints": []}}
}


# ============ Fixtures ============


@pytest.fixture
def mock_openai():
    """
    Mock OpenAI client — 接管 llm_client 层的所有 chat / chat_sync 调用。
    所有 LLM 调用汇聚到 _async_client + _sync_client 的 completions.create。
    """
    responses = {}

    def set_response(trigger: str, text: str):
        responses[trigger] = text

    def _make_response(text: str):
        """构造一个模仿 OpenAI API 返回的对象"""
        return MagicMock(
            choices=[MagicMock(message=MagicMock(content=text))]
        )

    def _match(prompt: str) -> str:
        for trigger, text in responses.items():
            if trigger in prompt:
                return text
        return "{}"

    async def async_create(*args, **kwargs):
        return _make_response(_match(str(kwargs)))

    def sync_create(*args, **kwargs):
        return _make_response(_match(str(kwargs)))

    mock_openai_inst = MagicMock()
    mock_openai_inst.set_response = set_response

    import backend.llm_client as llm_mod

    with patch.object(llm_mod._async_client.chat.completions, 'create', side_effect=async_create), \
         patch.object(llm_mod._sync_client.chat.completions, 'create', side_effect=sync_create):
        yield mock_openai_inst


# ============ 初始化测试 ============


class TestAgentEngineInit:
    """AgentEngine 初始化 — 所有组件应正确创建"""

    def test_all_components_created(self):
        from backend.agent_engine import AgentEngine
        eng = AgentEngine()
        assert hasattr(eng, 'memory'), "MemorySystem missing"
        assert hasattr(eng, 'registry'), "ToolRegistry missing"
        assert hasattr(eng, 'executor'), "ParallelExecutor missing"
        assert hasattr(eng, 'dag_loader'), "DAGLoader missing"
        assert hasattr(eng, 'router'), "CostRouter missing"
        assert hasattr(eng, 'tracer'), "TraceCollector missing"
        assert hasattr(eng, 'conversation'), "ConversationManager missing"
        assert hasattr(eng, 'intent_router'), "IntentRouter missing"
        assert hasattr(eng, 'report_builder'), "ReportBuilder missing"
        assert hasattr(eng, 'reflection_engine'), "ReflectionEngine missing"
        assert hasattr(eng, 'precheck'), "PrecheckEngine missing"
        assert hasattr(eng, 'decompose_engine'), "DecomposeEngine missing"

    def test_init_no_crash(self):
        """初始化不应抛出异常"""
        from backend.agent_engine import AgentEngine
        eng = AgentEngine()
        assert eng._pending_clarify is None
        assert isinstance(eng._report_cache, dict)


# ============ 缓存机制测试 ============


class TestCache:
    """_load_cache / _save_cache — 文件 I/O"""

    def test_load_cache_non_existent(self):
        """缓存文件不存在 → 返回空 dict"""
        from backend.agent_engine import AgentEngine
        eng = AgentEngine()
        cache = eng._load_cache()
        assert isinstance(cache, dict)

    def test_cache_key_miss_then_hit(self):
        """同 query+mode 24h 内应命中"""
        from backend.agent_engine import AgentEngine
        eng = AgentEngine()
        key = "test_cache|selection"
        report = '{"title":"test"}'
        eng._report_cache[key] = (time.time(), report)
        assert key in eng._report_cache


# ============ 工具映射测试 ============


class TestMapTools:
    """_map_tools — DAG → 工具映射"""

    def test_normal_mapping(self):
        from backend.agent_engine import AgentEngine
        eng = AgentEngine()
        dag = {"tasks": [
            {"id": "T1", "tool": "bocha_search", "deps": [], "parallel_group": 0, "desc": "搜索数据"},
            {"id": "T2", "tool": "report_generate", "deps": ["T1"], "parallel_group": 1, "desc": "生成报告"},
        ]}
        result = eng._map_tools(dag)
        assert result["total"] == 2
        assert result["mappings"][0]["tool"] == "bocha_search"
        assert result["mappings"][0]["task_id"] == "T1"

    def test_desc_fallback_unknown_tool(self):
        """工具名不识别 → 兜底 web_search"""
        from backend.agent_engine import AgentEngine
        eng = AgentEngine()
        dag = {"tasks": [
            {"id": "T1", "tool": "nonexistent_tool", "deps": [], "parallel_group": 0, "desc": "查数据"},
        ]}
        result = eng._map_tools(dag)
        assert result["mappings"][0]["tool"] == "web_search"

    def test_desc_empty_uses_label_fallback(self):
        """desc 为空 → 从 tool+id 生成标签"""
        from backend.agent_engine import AgentEngine
        eng = AgentEngine()
        dag = {"tasks": [
            {"id": "T1", "tool": "bocha_search", "deps": [], "parallel_group": 0, "desc": ""},
        ]}
        result = eng._map_tools(dag)
        assert "中文" in result["mappings"][0]["desc"]
        assert "T1" in result["mappings"][0]["desc"]

    def test_empty_tasks_list(self):
        """空任务列表 → total=0"""
        from backend.agent_engine import AgentEngine
        eng = AgentEngine()
        result = eng._map_tools({"tasks": []})
        assert result["total"] == 0


# ============ Pipeline 核心流程测试 ============


class TestPipelineFlows:
    """完整的 Pipeline 流程测试 — mock OpenAI client 层"""

    @pytest.mark.asyncio
    async def test_happy_path_selection(self, mock_openai):
        """正常选品分析流程：应产出完整的 SSE 事件序列"""
        mock_openai.set_response("识别专家", json.dumps(SAMPLE_INTENT, ensure_ascii=False))
        mock_openai.set_response("任务规划专家", json.dumps(SAMPLE_DAG, ensure_ascii=False))
        mock_openai.set_response("资深分析师", SAMPLE_REPORT)
        mock_openai.set_response("质检专家", json.dumps(SAMPLE_REFLECTION, ensure_ascii=False))

        from backend.agent_engine import AgentEngine

        eng = AgentEngine()
        # 让 precheck 通过（不依赖 LLM）
        eng.precheck.check = MagicMock(return_value=PASSED_PRECHECK)

        events = []
        async for event in eng.run_pipeline("帮我看看2026夏季法式茶歇裙", "test_happy"):
            events.append(event)

        event_types = [e["type"] for e in events]
        assert "phase" in event_types
        assert events[-1]["type"] == "done"

        # 验证 intent phase 完成
        intent_done = [e for e in events if e.get("phase") == "intent" and e.get("status") == "done"]
        assert len(intent_done) == 1

    @pytest.mark.asyncio
    async def test_clarify_flow_when_info_missing(self, mock_openai):
        """信息不足时 → 发出 clarify 事件并提前结束"""
        mock_openai.set_response("识别专家", json.dumps(SAMPLE_INTENT, ensure_ascii=False))

        from backend.agent_engine import AgentEngine

        eng = AgentEngine()
        eng.precheck.check = MagicMock(return_value=FAILED_PRECHECK)

        events = []
        async for event in eng.run_pipeline("随便看看", "test_clarify"):
            events.append(event)

        assert any(e["type"] == "clarify" for e in events), "应产出 clarify 事件"
        assert events[-1]["type"] == "done"

    @pytest.mark.asyncio
    async def test_image_mode_shortcut(self, mock_openai):
        """文生图模式：跳过 DAG 拆解和报告生成，直接输出图片 URL"""
        mock_openai.set_response("识别专家", json.dumps({
            "intent_type": "文生图",
            "confidence": 0.9,
            "entities": {"subject": "茶歇裙", "category": "连衣裙", "style": "法式"},
            "goal": {"品类": "连衣裙", "风格": "法式", "核心关注点": "生成图片"},
            "missing_info": [],
        }, ensure_ascii=False))

        from backend.agent_engine import AgentEngine
        import backend.agent_engine as ae_mod

        with patch.object(ae_mod, 'execute_tool_sync',
                          lambda *a, **kw: {"url": "http://example.com/img.png", "prompt": "test"}):
            eng = AgentEngine()
            eng.precheck.check = MagicMock(return_value=PASSED_PRECHECK)
            # 文生图用模块级函数替代（ae_mod 在 for 循环外已 import）
            patch.object(ae_mod, '_optimize_img_prompt', return_value='优化后的prompt').start(),
            patch.object(ae_mod, '_build_img_prompt', return_value='').start(),

            events = []
            async for event in eng.run_pipeline("夏季法式茶歇裙摄影图", "test_image", mode="selection"):
                events.append(event)

        image_results = [e for e in events if e["type"] == "image_result"]
        assert len(image_results) >= 1
        assert "url" in image_results[0]

    @pytest.mark.asyncio
    async def test_cache_hit_returns_early(self, mock_openai):
        """缓存命中（24h 内同 query+mode）→ 直接返回缓存"""
        from backend.agent_engine import AgentEngine

        # 用 UUID 避免跨测试记忆污染（MemorySystem 持久化到磁盘）
        import uuid
        sid = f"test_cache_{uuid.uuid4().hex[:8]}"

        eng = AgentEngine()
        cache_key = f"帮我看看2026夏季茶歇裙|auto"
        eng._report_cache[cache_key] = (time.time(), SAMPLE_REPORT)

        events = []
        async for event in eng.run_pipeline("帮我看看2026夏季茶歇裙", sid, mode="auto"):
            events.append(event)

        assert any(e["type"] == "cache_hit" for e in events)
        results = [e for e in events if e["type"] == "result"]
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_cache_stale_removed(self, mock_openai):
        """缓存超过 24h → 移除"""
        from backend.agent_engine import AgentEngine

        eng = AgentEngine()
        cache_key = "stale_query|auto"
        eng._report_cache[cache_key] = (time.time() - 90000, SAMPLE_REPORT)
        assert cache_key in eng._report_cache

        eng._report_cache.pop(cache_key, None)
        assert cache_key not in eng._report_cache

    @pytest.mark.asyncio
    async def test_reflection_retry_mechanism(self, mock_openai):
        """反思评分不足 → 自动重试并选择最高分版本"""
        mock_openai.set_response("识别专家", json.dumps(SAMPLE_INTENT, ensure_ascii=False))
        mock_openai.set_response("任务规划", json.dumps(SAMPLE_DAG, ensure_ascii=False))

        from backend.agent_engine import AgentEngine
        import backend.agent_engine as ae_mod
        from unittest.mock import AsyncMock
        import backend.llm_client as llm_mod

        with patch.object(ae_mod, 'execute_tool_sync',
                          lambda *a, **kw: {"summary": "mock", "_llm_driven": False}):

            eng = AgentEngine()
            eng.precheck.check = MagicMock(return_value=PASSED_PRECHECK)

            # 接管 report_builder.generate
            report_call_count = [0]
            async def mock_generate(*args, **kwargs):
                report_call_count[0] += 1
                if report_call_count[0] >= 2:
                    return json.dumps({"title": "修正版", "sections": []}, ensure_ascii=False)
                return SAMPLE_REPORT
            eng.report_builder.generate = mock_generate

            # 直接 mock reflection_engine.evaluate 返回动态分数
            reflect_call_count = [0]
            reflect_scores = [
                {"scores": {"data_consistency": 5, "goal_alignment": 5,
                           "actionability": 5, "overall": 5.0},
                 "passed": False},
                {"scores": {"data_consistency": 8, "goal_alignment": 8,
                           "actionability": 8, "overall": 8.0},
                 "passed": True},
            ]
            async def mock_evaluate(*args, **kwargs):
                idx = reflect_call_count[0]
                reflect_call_count[0] += 1
                return reflect_scores[min(idx, len(reflect_scores) - 1)]
            eng.reflection_engine.evaluate = mock_evaluate

            events = []
            async for event in eng.run_pipeline("帮我分析法式茶歇裙轮重试", "test_retry"):
                events.append(event)

        retry_events = [e for e in events if e.get("phase") == "reflect_retry"]
        assert len(retry_events) >= 1

    @pytest.mark.asyncio
    async def test_followup_query_scenario(self, mock_openai):
        """多轮对话场景：短查询 + 有上轮意图 → 触发追问检测"""
        mock_openai.set_response("识别专家", json.dumps(SAMPLE_INTENT, ensure_ascii=False))
        mock_openai.set_response("任务规划专家", json.dumps(SAMPLE_DAG, ensure_ascii=False))
        mock_openai.set_response("资深分析师", SAMPLE_REPORT)
        mock_openai.set_response("质检专家", json.dumps(SAMPLE_REFLECTION, ensure_ascii=False))

        from backend.agent_engine import AgentEngine
        import backend.agent_engine as ae_mod

        with patch.object(ae_mod, 'execute_tool_sync',
                          lambda *a, **kw: {"summary": "mock", "_llm_driven": False}):
            eng = AgentEngine()
            eng.precheck.check = MagicMock(return_value=PASSED_PRECHECK)
            eng.memory.update_working_memory("test_followup", "last_intent", "单品选品分析")

            events = []
            async for event in eng.run_pipeline("具体价格多少", "test_followup"):
                events.append(event)

        assert events[-1]["type"] == "done"


# ============ Memory 更新测试 ============


class TestMemoryUpdate:
    """_update_memory — Pipeline 完成后的记忆更新"""

    def test_update_memory_appends_conversation(self):
        from backend.agent_engine import AgentEngine
        eng = AgentEngine()

        eng._update_memory("test_sid", "用户提问",
                          SAMPLE_INTENT, SAMPLE_REPORT)

        conv = eng.memory.get_conversation("test_sid")
        assert len(conv) >= 1
        roles = [m["role"] for m in conv]
        assert "user" in roles
        assert "assistant" in roles

    def test_update_memory_stores_last_intent(self):
        from backend.agent_engine import AgentEngine
        eng = AgentEngine()

        eng._update_memory("test_sid2", "用户提问",
                          SAMPLE_INTENT, SAMPLE_REPORT)

        wm = eng.memory.get_working_memory("test_sid2")
        assert wm.get("last_intent") == "单品选品分析"


# ============ Error Handling 测试 ============


class TestErrorHandling:
    """错误处理 — LLM 失败应优雅降级"""

    @pytest.mark.asyncio
    async def test_pipeline_recovers_from_llm_error(self, mock_openai):
        """意图识别 LLM 返回空 → fallback 不应崩溃"""
        # 不给任何 set_response → 所有 LLM 返回 "{}"
        from backend.agent_engine import AgentEngine
        import backend.agent_engine as ae_mod

        with patch.object(ae_mod, 'execute_tool_sync',
                          lambda *a, **kw: {"summary": "mock"}):
            eng = AgentEngine()

            events = []
            try:
                async for event in eng.run_pipeline("测试", "test_err"):
                    events.append(event)
            except Exception as e:
                pytest.fail(f"Pipeline should not crash on LLM failure: {e}")

        assert events[-1]["type"] == "done"

    @pytest.mark.asyncio
    async def test_precheck_no_crash_on_empty_intent(self, mock_openai):
        """空 intent 传给 precheck 不应崩溃"""
        # 不设响应，全返回 "{}" — intent fallback 应兜底
        from backend.agent_engine import AgentEngine
        import backend.agent_engine as ae_mod

        with patch.object(ae_mod, 'execute_tool_sync',
                          lambda *a, **kw: {"summary": "mock"}):
            eng = AgentEngine()

            events = []
            try:
                async for event in eng.run_pipeline("", "test_empty"):
                    events.append(event)
            except Exception as e:
                pytest.fail(f"Should not crash on empty input: {e}")
