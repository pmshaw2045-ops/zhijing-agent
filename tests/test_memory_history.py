"""测试 memory.py — find_related_analyses 同类目历史检索"""
import sys
import os
from pathlib import Path

import pytest
from backend.memory import MemorySystem


@pytest.fixture
def memory(tmp_path):
    """每个测试使用独立的临时目录，mock embed_text 使其回退到关键词匹配"""
    import backend.memory as mem_mod
    from unittest.mock import patch
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
    # mock embed_text 使其回退到关键词匹配（不调真实 LLM）
    async def _mock_embed(*args):
        return None
    import unittest.mock as mock
    with mock.patch.object(ms, 'embed_text', _mock_embed):
        yield ms
    mem_mod.DATA_DIR = old_dir  # 恢复


class TestFindRelatedAnalyses:
    @pytest.mark.asyncio
    async def test_find_by_category(self, memory):
        """按类目查找"""
        results, info = await memory.find_related_analyses("test-sid", "茶歇裙")
        assert len(results) >= 1
        # 结果中应包含茶歇裙
        assert any(r.get("category") == "茶歇裙" for r in results)

    @pytest.mark.asyncio
    async def test_find_by_intent_type(self, memory):
        """按意图类型查找"""
        results, info = await memory.find_related_analyses("test-sid", "", "定价策略分析")
        assert len(results) >= 1
        assert any(r.get("intent") == "定价策略分析" for r in results)

    @pytest.mark.asyncio
    async def test_find_by_category_contains(self, memory):
        """类目包含关系：\"连衣裙\" 匹配 \"连衣裙\""""
        results, info = await memory.find_related_analyses("test-sid", "连衣裙")
        assert len(results) >= 2

    @pytest.mark.asyncio
    async def test_max_3_results(self, memory):
        """最多返回 3 条"""
        results, info = await memory.find_related_analyses("test-sid", "连衣裙")
        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_order_by_time_desc(self, memory):
        """按时间倒序"""
        results, info = await memory.find_related_analyses("test-sid", "连衣裙")
        if len(results) >= 2:
            assert results[0].get("timestamp", 0) >= results[1].get("timestamp", 0)

    @pytest.mark.asyncio
    async def test_no_match(self, memory):
        """无匹配返回空列表"""
        results, info = await memory.find_related_analyses("test-sid", "不存在品类")
        assert results == []

    @pytest.mark.asyncio
    async def test_empty_session_id(self, memory):
        """空 session_id 返回空"""
        results, info = await memory.find_related_analyses("", "茶歇裙")
        assert results == []

    @pytest.mark.asyncio
    async def test_empty_category_and_intent(self, memory):
        """无类目和意图时返回空"""
        results, info = await memory.find_related_analyses("test-sid", "", "")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_info_contains_query(self, memory):
        """检索信息中包含 query 和 method"""
        results, info = await memory.find_related_analyses("test-sid", "连衣裙")
        assert "query" in info
        assert "method" in info
        assert "latency_ms" in info

    @pytest.mark.asyncio
    async def test_synonym_matching(self, memory):
        """同义词桥接：\"茶歇裙\" 匹配 category=\"连衣裙\" 的历史记录"""
        results, info = await memory.find_related_analyses("test-sid", "茶歇裙")
        # "茶歇裙" 在连衣裙同义词表内，应匹配到 category="连衣裙" 的记录
        assert len(results) >= 1
        assert any(r.get("category") == "连衣裙" for r in results)
