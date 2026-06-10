"""server.py 集成测试 — FastAPI 端点 + SSE 流

测试策略：
- 使用 FastAPI TestClient (httpx)
- mock AgentEngine.run_pipeline 控制 SSE 输出（不调真实 LLM）
- 健康检查、记忆查询、指标端点直测（不依赖 LLM）
- SSE 端点验证事件序列、错误处理、400 输入校验

不测得：
- 真实 LLM 调用（由 agent_engine 测试覆盖）
- 浏览器缓存行为（由 curl 手测）
"""
import sys, json, pytest, os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# # sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))


# ============ Test Data ============

SAMPLE_SSE_EVENTS = [
    {"type": "phase", "phase": "intent", "status": "done", "data": {"intent_type": "单品选品分析"}},
    {"type": "phase", "phase": "precheck", "status": "done", "data": {"passed": True}},
    {"type": "phase", "phase": "decompose", "status": "done", "label": "LLM 自主拆解 ✅",
     "data": {"_llm_generated": True, "tasks": [{"id": "T1", "tool": "bocha_search"}]}},
    {"type": "phase", "phase": "execute", "status": "done", "data": {"all_completed": True}},
    {"type": "result", "content": '{"title":"测试报告","sections":[]}'},
    {"type": "quality_review", "data": {"passed": True, "scores": {"overall": 8}}},
    {"type": "done"},
]

CLARIFY_SSE_EVENTS = [
    {"type": "clarify", "message": "请明确您要分析的品类"},
    {"type": "done"},
]


# ============ Fixtures ============


@pytest.fixture(autouse=True)
def setup_env():
    """确保测试环境使用测试 API key"""
    old = {}
    for k in ["DEEPSEEK_API_KEY", "ARK_API_KEY", "TAVILY_API_KEY", "BOCHA_API_KEY"]:
        old[k] = os.environ.get(k)
        os.environ[k] = "test-key"
    yield
    for k, v in old.items():
        if v is None:
            del os.environ[k]
        else:
            os.environ[k] = v


@pytest.fixture
def mock_pipeline():
    """Mock run_pipeline 返回测试 SSE 事件"""
    with patch("backend.server.engine") as mock_engine:
        mock_engine.run_pipeline = AsyncMock()
        yield mock_engine


def _make_pipeline_mock(events):
    """构造 async generator 模拟 run_pipeline"""
    async def _mock(*args, **kwargs):
        for ev in events:
            yield ev
            await asyncio.sleep(0)
    return _mock


# ============ 测试类 ============


class TestHealth:
    """GET /api/health"""

    def test_health_returns_ok(self):
        from backend.server import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["engine"] == "ready"
        assert "models" in data
        assert "flash" in data["models"]

    def test_health_includes_session_count(self):
        from backend.server import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/api/health")
        data = resp.json()
        assert isinstance(data.get("sessions"), (int, str))


class TestMetrics:
    """GET /api/metrics"""

    def test_metrics_returns_counts(self):
        from backend.server import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/api/metrics")
        assert resp.status_code == 200
        data = resp.json()
        # metrics 应包含请求计数或 token 计数
        assert isinstance(data, dict)


class TestRoot:
    """GET /"""

    def test_root_returns_html(self):
        from backend.server import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "</html>" in resp.text

    def test_root_has_cache_control(self):
        from backend.server import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/")
        assert "no-cache" in resp.headers.get("cache-control", "")


class TestChatSSE:
    """POST /api/chat — SSE 流"""

    @pytest.mark.asyncio
    async def test_empty_message_400(self):
        from backend.server import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.post("/api/chat", json={"message": ""})
        assert resp.status_code == 400
        data = resp.json()
        assert "error" in data

    @pytest.mark.asyncio
    async def test_successful_sse_flow(self):
        """完整 SSE 事件序列应包含: phase → result → done"""
        # 导入时触发 engine 初始化 — 我们 patch engine 对象
        import backend.server as server_mod

        async def mock_pipeline(*args, **kwargs):
            for ev in SAMPLE_SSE_EVENTS:
                yield ev

        with patch.object(server_mod.engine, 'run_pipeline', mock_pipeline):
            from fastapi.testclient import TestClient
            client = TestClient(server_mod.app)
            resp = client.post("/api/chat", json={"message": "茶歇裙分析"})

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        # 解析 SSE 事件
        events = []
        for line in resp.text.strip().split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        # 验证事件序列
        assert len(events) == len(SAMPLE_SSE_EVENTS)
        assert events[-1]["type"] == "done"
        assert events[-2]["type"] == "quality_review"
        # 验证 _llm_generated 被传递
        decompose_event = next(e for e in events if e.get("phase") == "decompose")
        assert decompose_event["data"]["_llm_generated"] is True
        assert "LLM 自主拆解" in decompose_event.get("label", "")

    @pytest.mark.asyncio
    async def test_clarify_flow(self):
        """clarify 事件后应跟 done"""
        import backend.server as server_mod

        async def mock_pipeline(*args, **kwargs):
            for ev in CLARIFY_SSE_EVENTS:
                yield ev

        with patch.object(server_mod.engine, 'run_pipeline', mock_pipeline):
            from fastapi.testclient import TestClient
            client = TestClient(server_mod.app)
            resp = client.post("/api/chat", json={"message": "模糊输入"})

        events = []
        for line in resp.text.strip().split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        assert len(events) == 2
        assert events[0]["type"] == "clarify"
        assert events[1]["type"] == "done"

    @pytest.mark.asyncio
    async def test_pipeline_error_returns_error_event(self):
        """pipeline 抛异常 → 服务端返回 error event"""
        import backend.server as server_mod

        async def mock_pipeline(*args, **kwargs):
            """async generator that raises"""
            raise ValueError("LLM API 超时")
            yield  # pragma: no cover — never reached

        with patch.object(server_mod.engine, 'run_pipeline', mock_pipeline):
            from fastapi.testclient import TestClient
            client = TestClient(server_mod.app)
            resp = client.post("/api/chat", json={"message": "茶歇裙"})

        events = []
        for line in resp.text.strip().split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        assert len(events) >= 1
        error_event = next((e for e in events if e.get("type") == "error"), None)
        assert error_event is not None
        assert error_event.get("message") == "服务内部错误，请重试"

    @pytest.mark.asyncio
    async def test_session_id_propagation(self):
        """session_id 应传递到 pipeline"""
        import backend.server as server_mod
        captured = {}

        async def mock_pipeline(message, session_id, mode, clarify_answer):
            captured["session_id"] = session_id
            captured["mode"] = mode
            return
            yield  # make it async generator

        with patch.object(server_mod.engine, 'run_pipeline', mock_pipeline):
            from fastapi.testclient import TestClient
            client = TestClient(server_mod.app)
            client.post("/api/chat", json={
                "message": "分析茶歇裙",
                "session_id": "test_sess_001",
                "mode": "selection"
            })

        assert captured.get("session_id") == "test_sess_001"
        assert captured.get("mode") == "selection"

    @pytest.mark.asyncio
    async def test_default_mode_selection(self):
        """未指定 mode → 默认 selection (通过 run_pipeline 参数验证)"""
        import backend.server as server_mod
        captured = {}

        async def mock_pipeline(message, session_id, mode, clarify_answer):
            captured["mode"] = mode
            return
            yield

        with patch.object(server_mod.engine, 'run_pipeline', mock_pipeline):
            from fastapi.testclient import TestClient
            client = TestClient(server_mod.app)
            client.post("/api/chat", json={"message": "分析茶歇裙"})

        assert captured.get("mode") == "selection"


class TestMemoryEndpoints:
    """GET /api/memory/{session_id}"""

    def test_memory_returns_session(self):
        from backend.server import app
        from fastapi.testclient import TestClient

        # 先用 chat 创建会话
        client = TestClient(app)
        chat_resp = client.post("/api/chat", json={"message": "茶歇裙", "session_id": "test_mem_001"})

        # 再查记忆
        resp = client.get("/api/memory/test_mem_001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "test_mem_001"
        assert "stats" in data
        assert "conversation" in data
        # 记忆应有用户消息
        if data.get("conversation"):
            assert data["conversation"][0]["role"] == "user"

    def test_memory_conversation_endpoint(self):
        from backend.server import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        client.post("/api/chat", json={"message": "茶歇裙", "session_id": "test_mem_002"})
        resp = client.get("/api/memory/test_mem_002/conversation")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "test_mem_002"
        assert "conversation" in data
        assert "count" in data
