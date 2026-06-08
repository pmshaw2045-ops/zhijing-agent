"""测试 store.py — SQLiteBackend 存储后端"""
import os
import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

# 确保测试不依赖真实 .env（覆盖可能干扰的 env vars）
os.environ["STORE_BACKEND"] = "sqlite"

import pytest
from store import SQLiteBackend, migrate_json_to_sqlite


@pytest.fixture
def db_path():
    """每个测试使用独立的临时数据库文件"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    yield path
    # 清理
    try:
        backend = SQLiteBackend(path)
        backend.close()
        path.unlink(missing_ok=True)
    except Exception:
        pass


@pytest.fixture
def backend(db_path):
    """创建一个指向临时文件的 SQLiteBackend"""
    bk = SQLiteBackend(db_path)
    yield bk
    bk.close()


# ====== Session CRUD ======


class TestSessionCRUD:
    def test_get_session_empty(self, backend):
        """不存在的 session 返回空 dict"""
        assert backend.get_session("nonexistent") == {}

    def test_set_and_get_session(self, backend):
        """写入后能读取"""
        data = {"intent": "选品分析", "messages": [{"role": "user", "content": "你好"}]}
        backend.set_session("sid-1", data)
        result = backend.get_session("sid-1")
        assert result["intent"] == "选品分析"
        assert len(result["messages"]) == 1

    def test_set_overwrites(self, backend):
        """重复 set_session 覆盖旧数据"""
        backend.set_session("sid-1", {"version": 1})
        backend.set_session("sid-1", {"version": 2})
        result = backend.get_session("sid-1")
        assert result["version"] == 2

    def test_has_session_true(self, backend):
        """存在的 session has_session 返回 True"""
        backend.set_session("sid-1", {"x": 1})
        assert backend.has_session("sid-1") is True

    def test_has_session_false(self, backend):
        """不存在的 session has_session 返回 False"""
        assert backend.has_session("nope") is False

    def test_session_count(self, backend):
        """session_count 返回准确的数量"""
        assert backend.session_count() == 0
        backend.set_session("a", {})
        backend.set_session("b", {})
        backend.set_session("c", {})
        assert backend.session_count() == 3

    def test_session_with_complex_data(self, backend):
        """含嵌套 dict/list 的数据"""
        data = {
            "nested": {"list": [1, 2, {"k": "v"}]},
            "empty_dict": {},
            "null_value": None,
            "unicode": "中文测试",
        }
        backend.set_session("complex", data)
        result = backend.get_session("complex")
        assert result["nested"]["list"][2]["k"] == "v"
        assert result["unicode"] == "中文测试"

    def test_multiple_sessions_independent(self, backend):
        """多个 session 互不干扰"""
        backend.set_session("sid-a", {"data": "A"})
        backend.set_session("sid-b", {"data": "B"})
        assert backend.get_session("sid-a")["data"] == "A"
        assert backend.get_session("sid-b")["data"] == "B"
        assert backend.session_count() == 2


# ====== Long-term Storage ======


class TestLongTerm:
    def test_get_long_term_empty(self, backend):
        """空数据库返回默认结构"""
        lt = backend.get_long_term()
        assert "domains" in lt
        assert "brands" in lt
        assert "seasons" in lt
        assert "knowledge_snippets" in lt

    def test_set_and_get_long_term(self, backend):
        """长期记忆可以读写"""
        lt = {
            "domains": {"女装": {"trends": ["法式"]}},
            "brands": {"品牌A": {"price_level": "中高端"}},
            "seasons": {},
            "platforms": {"天猫": {"share": 0.4}},
            "user_preferences": {"风格": ["简约", "法式"]},
            "knowledge_snippets": ["连衣裙是女装核心品类"],
        }
        backend.set_long_term(lt)
        result = backend.get_long_term()
        assert result["domains"]["女装"]["trends"] == ["法式"]
        assert result["brands"]["品牌A"]["price_level"] == "中高端"
        assert "连衣裙" in result["knowledge_snippets"][0]

    def test_set_long_term_overwrites(self, backend):
        """重复 set_long_term 覆盖"""
        backend.set_long_term({"domains": {"旧": {}}, "brands": {}, "seasons": {},
                                "platforms": {}, "user_preferences": {},
                                "knowledge_snippets": ["旧数据"]})
        backend.set_long_term({"domains": {"新": {}}, "brands": {}, "seasons": {},
                                "platforms": {}, "user_preferences": {},
                                "knowledge_snippets": ["新数据"]})
        result = backend.get_long_term()
        assert "新" in result["domains"]
        assert "旧" not in result["domains"]
        assert result["knowledge_snippets"] == ["新数据"]


# ====== Migration ======


class TestMigration:
    def test_migrate_nonexistent_json(self, backend, db_path):
        """不存在的 JSON 文件返回 0"""
        count = migrate_json_to_sqlite(db_path.parent / "nonexistent.json")
        assert count == 0

    def test_migrate_json_to_sqlite(self, backend, db_path):
        """从 JSON 文件迁移到 SQLite"""
        json_path = db_path.parent / "test_memory.json"
        data = {
            "sessions": {
                "s1": {"intent": "选品", "messages": []},
                "s2": {"intent": "趋势", "messages": []},
            },
            "long_term": {"domains": {"女装": {}}, "brands": {}, "seasons": {},
                          "platforms": {}, "user_preferences": {},
                          "knowledge_snippets": []},
        }
        json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        try:
            count = migrate_json_to_sqlite(json_path, db_path)
            assert count == 2
            assert backend.has_session("s1") is True
            assert backend.has_session("s2") is True
        finally:
            json_path.unlink(missing_ok=True)


# ====== Edge Cases ======


class TestEdgeCases:
    def test_session_data_empty_dict(self, backend):
        """空 dict 作为 session 数据"""
        backend.set_session("empty", {})
        assert backend.get_session("empty") == {}

    def test_long_term_empty_knowledge(self, backend):
        """空 knowledge_snippets 不报错"""
        lt = {"domains": {}, "brands": {}, "seasons": {},
              "platforms": {}, "user_preferences": {},
              "knowledge_snippets": []}
        backend.set_long_term(lt)
        result = backend.get_long_term()
        assert result["knowledge_snippets"] == []

    def test_close_then_reopen(self, db_path):
        """关闭后重新打开，数据持久化"""
        bk1 = SQLiteBackend(db_path)
        bk1.set_session("persist", {"data": "持久化测试"})
        bk1.close()

        bk2 = SQLiteBackend(db_path)
        result = bk2.get_session("persist")
        bk2.close()
        assert result["data"] == "持久化测试"
