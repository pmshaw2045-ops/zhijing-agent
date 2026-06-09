"""测试 memory.py — find_related_analyses 同类目历史检索"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import pytest
from memory import MemorySystem


@pytest.fixture
def memory(tmp_path):
    """每个测试使用独立的临时目录"""
    import memory as mem_mod
    # 临时替换 DATA_DIR
    old_dir = mem_mod.DATA_DIR
    mem_mod.DATA_DIR = tmp_path
    ms = mem_mod.MemorySystem()
    # 直接构造历史数据
    session = ms._ensure_session("test-sid")
    session["working"] = {
        "context": {
            "analysis_history": [
                {"query": "分析法式茶歇裙", "intent": "单品选品分析", "category": "茶歇裙",
                 "key_findings": "高增长品类，推荐切入", "params": {}, "timestamp": 1000},
                {"query": "对比太平鸟和伊芙丽", "intent": "多品牌竞品对标", "category": "连衣裙",
                 "key_findings": "太平鸟价格带更宽", "params": {}, "timestamp": 2000},
                {"query": "泡泡袖趋势分析", "intent": "品类趋势洞察", "category": "泡泡袖",
                 "key_findings": "泡泡袖搜索热度上升40%", "params": {}, "timestamp": 3000},
                {"query": "夏装连衣裙定价策略", "intent": "定价策略分析", "category": "连衣裙",
                 "key_findings": "主力价格带199-299", "params": {}, "timestamp": 4000},
            ]
        }
    }
    ms.mark_dirty()
    yield ms
    mem_mod.DATA_DIR = old_dir  # 恢复


class TestFindRelatedAnalyses:
    def test_find_by_category(self, memory):
        """按类目查找"""
        result = memory.find_related_analyses("test-sid", "茶歇裙")
        assert len(result) == 1
        assert result[0]["category"] == "茶歇裙"

    def test_find_by_intent_type(self, memory):
        """按意图类型查找"""
        result = memory.find_related_analyses("test-sid", "", "定价策略分析")
        assert len(result) == 1
        assert result[0]["intent"] == "定价策略分析"

    def test_find_by_category_contains(self, memory):
        """类目包含关系："连衣裙" 匹配 "连衣裙" """
        result = memory.find_related_analyses("test-sid", "连衣裙")
        assert len(result) >= 2  # 太平鸟 + 夏装定价

    def test_max_3_results(self, memory):
        """最多返回 3 条"""
        result = memory.find_related_analyses("test-sid", "连衣裙")
        assert len(result) <= 3

    def test_order_by_time_desc(self, memory):
        """按时间倒序"""
        result = memory.find_related_analyses("test-sid", "连衣裙")
        if len(result) >= 2:
            assert result[0]["timestamp"] >= result[1]["timestamp"]

    def test_no_match(self, memory):
        """无匹配返回空列表"""
        result = memory.find_related_analyses("test-sid", "不存在品类")
        assert result == []

    def test_empty_session_id(self, memory):
        """空 session_id 返回空"""
        assert memory.find_related_analyses("", "茶歇裙") == []

    def test_empty_category_and_intent(self, memory):
        """无类目和意图时返回空"""
        assert memory.find_related_analyses("test-sid", "", "") == []
