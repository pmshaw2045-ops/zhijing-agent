"""测试 conversation.py v2 — 实体提取 + LLM 兜底 + goal 合并"""
import sys
import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import pytest
from backend.conversation import ConversationManager, Scenario


@pytest.fixture
def mgr():
    """每个测试使用新的 ConversationManager 实例"""
    return ConversationManager()


# ====== 场景检测（关键词层） ======


class TestDetectScenario:
    def test_new_query(self, mgr):
        """全新的长查询 → NEW_QUERY"""
        assert mgr.detect_scenario("帮我分析2026夏季法式茶歇裙的选品机会") == Scenario.NEW_QUERY

    def test_followup_deepen_keyword(self, mgr):
        """含"详细"关键词 → FOLLOWUP_DEEPEN"""
        assert mgr.detect_scenario("详细说说茶歇裙的面料") == Scenario.FOLLOWUP_DEEPEN

    def test_followup_compare_keyword(self, mgr):
        """含"对比"关键词 → FOLLOWUP_COMPARE"""
        assert mgr.detect_scenario("对比伊芙丽和太平鸟") == Scenario.FOLLOWUP_COMPARE

    def test_followup_modify_keyword(self, mgr):
        """含"改成"关键词 → FOLLOWUP_MODIFY"""
        assert mgr.detect_scenario("改成泡泡袖") == Scenario.FOLLOWUP_MODIFY

    def test_new_topic_keyword(self, mgr):
        """含"换个"关键词 → NEW_TOPIC"""
        assert mgr.detect_scenario("换个话题，分析女装趋势") == Scenario.NEW_TOPIC

    def test_short_query_with_context(self, mgr):
        """有上轮意图的短查询 → FOLLOWUP_DEEPEN"""
        assert mgr.detect_scenario("那泡泡袖呢", last_intent="selection") == Scenario.FOLLOWUP_DEEPEN


class TestDetectScenarioLLM:
    def test_llm_fallback_on_long_query_no_keyword(self, mgr):
        """关键词未命中但上轮有上下文 → LLM 兜底"""
        with patch("backend.conversation.chat_sync", return_value="followup_deepen"):
            result = mgr.detect_scenario("那泡泡袖的市场表现如何", last_intent="selection")
            assert result == Scenario.FOLLOWUP_DEEPEN

    def test_llm_returns_new_query(self, mgr):
        """LLM 判定为新查询（长查询绕过短查询启发式）"""
        with patch("backend.conversation.chat_sync", return_value="new_query"):
            result = mgr.detect_scenario("帮我分析2026秋季连衣裙的市场趋势和价格带分布情况以及消费者偏好变化", last_intent="selection")
            assert result == Scenario.NEW_QUERY

    def test_llm_failure_falls_back(self, mgr):
        """LLM 调用失败 → 返回 NEW_QUERY"""
        with patch("backend.conversation.chat_sync", side_effect=Exception("API error")):
            result = mgr.detect_scenario("帮我分析2026秋季连衣裙的市场趋势和价格带分布情况以及消费者偏好变化", last_intent="selection")
            assert result == Scenario.NEW_QUERY


# ====== 实体提取 ======


class TestExtractEntities:
    def test_that_pattern(self, mgr):
        """那泡泡袖呢 → 提取品类"""
        result = mgr.extract_entities_from_followup("那泡泡袖呢", {})
        assert result is not None
        assert result.get("品类") == "泡泡袖"

    def test_change_to_pattern(self, mgr):
        """换成夏装 → 提取品类"""
        result = mgr.extract_entities_from_followup("换成夏装连衣裙", {})
        assert result is not None
        assert result.get("品类") == "夏装连衣裙"

    def test_compare_with_pattern(self, mgr):
        """对比伊芙丽 → 提取竞品品牌"""
        result = mgr.extract_entities_from_followup("对比伊芙丽", {})
        assert result is not None
        assert "伊芙丽" in result.get("竞品品牌", [])

    def test_append_pattern(self, mgr):
        """追加泡泡袖 → 标记追加动作"""
        result = mgr.extract_entities_from_followup("追加泡泡袖元素", {})
        assert result is not None
        assert result.get("_action") == "append_category"

    def test_remove_pattern(self, mgr):
        """不要蕾丝 → 标记移除"""
        result = mgr.extract_entities_from_followup("不要蕾丝", {})
        assert result is not None
        assert result.get("_remove") == "蕾丝"

    def test_intent_switch(self, mgr):
        """换成品类趋势分析 → 意图切换"""
        result = mgr.extract_entities_from_followup("换成品类趋势分析", {})
        assert result is not None
        assert result.get("intent_type") == "品类趋势洞察"

    def test_intent_switch_pricing(self, mgr):
        """换成定价分析 → 意图切换"""
        result = mgr.extract_entities_from_followup("换成定价分析", {})
        assert result is not None
        assert result.get("intent_type") == "定价策略分析"

    def test_new_query_no_entities(self, mgr):
        """新查询无匹配 → None"""
        with patch("backend.conversation.chat_sync",
                   return_value="不是JSON{broken"):
            result = mgr.extract_entities_from_followup("帮我分析2026夏季连衣裙趋势", {})
        # LLM 兜底返回无效JSON → None
        assert result is None

    def test_has_entity_changes(self, mgr):
        """has_entity_changes 检测"""
        assert mgr.has_entity_changes("那泡泡袖呢") is True
        assert mgr.has_entity_changes("换成夏装") is True
        assert mgr.has_entity_changes("对比伊芙丽") is True
        assert mgr.has_entity_changes("帮我分析趋势") is False


# ====== Goal 合并 ======


class TestMergeGoal:
    def test_replace_scalar(self, mgr):
        """标量字段替换"""
        result = mgr.merge_goal({"品类": "茶歇裙", "风格": "法式"}, {"品类": "泡泡袖"})
        assert result["品类"] == "泡泡袖"
        assert result["风格"] == "法式"  # 未提及字段保留

    def test_append_brand(self, mgr):
        """竞品品牌追加"""
        result = mgr.merge_goal({"品类": "茶歇裙", "竞品品牌": ["太平鸟"]}, {"竞品品牌": ["伊芙丽"]})
        assert "太平鸟" in result["竞品品牌"]
        assert "伊芙丽" in result["竞品品牌"]
        assert len(result["竞品品牌"]) == 2

    def test_intent_switch_clears_goal(self, mgr):
        """意图切换清空旧 goal"""
        result = mgr.merge_goal({"品类": "茶歇裙", "风格": "法式"}, {"intent_type": "品类趋势洞察"})
        assert result == {}  # 不同意图的 goal 结构不同，清空

    def test_append_category_behavior(self, mgr):
        """追加品类"""
        result = mgr.merge_goal({"品类": "茶歇裙"}, {"品类": "泡泡袖", "_action": "append_category"})
        assert "茶歇裙" in result["品类"]
        assert "泡泡袖" in result["品类"]

    def test_remove_field(self, mgr):
        """移除字段"""
        result = mgr.merge_goal({"品类": "茶歇裙", "风格": "法式、蕾丝"}, {"_remove": "蕾丝"})
        assert "蕾丝" not in result["风格"]

    def test_empty_changes(self, mgr):
        """无变更 → 原样返回"""
        result = mgr.merge_goal({"品类": "茶歇裙"}, None)
        assert result == {"品类": "茶歇裙"}


# ====== 其他 ======


class TestHelpers:
    def test_is_followup(self, mgr):
        assert mgr.is_followup("继续详细说说") is True
        assert mgr.is_followup("帮我分析连衣裙趋势") is False

    def test_augment_query_backward_compat(self, mgr):
        """augment_query 保留兼容（当前是空操作）"""
        result = mgr.augment_query("测试", Scenario.NEW_QUERY)
        assert result == "测试"
