"""测试 intent_registry.py — 意图注册表完整性"""
import pytest
from intent_registry import (
    INTENT_REGISTRY, Complexity,
    route_by_name, get_en_to_cn, get_mode_fallback,
    get_all_names, get_complexity, get_intent_signals,
    get_decompose_rule, get_all_dags
)

EXPECTED_INTENTS = ["selection", "competitive", "trend", "copy", "pricing", "launch", "image"]


class TestRegistryCompleteness:
    """注册表完整性"""

    def test_all_intents_registered(self):
        for mode in EXPECTED_INTENTS:
            assert mode in INTENT_REGISTRY, f"Missing: {mode}"

    def test_each_intent_has_required_fields(self):
        required = ["mode", "name", "display", "complexity", "decompose_rule", "intent_signals", "dag"]
        for mode, info in INTENT_REGISTRY.items():
            for field in required:
                assert field in info, f"{mode} missing: {field}"

    def test_complexity_valid(self):
        for mode, info in INTENT_REGISTRY.items():
            assert isinstance(info["complexity"], Complexity), f"{mode} bad complexity"

    def test_dag_has_tasks(self):
        for mode, info in INTENT_REGISTRY.items():
            dag = info["dag"]
            assert "tasks" in dag, f"{mode} DAG missing tasks"
            assert len(dag["tasks"]) >= 1, f"{mode} DAG has 0 tasks"


class TestRegistryHelpers:
    """辅助函数"""

    def test_route_by_name(self):
        assert route_by_name("单品选品分析") == "selection"
        assert route_by_name("文生图") == "image"
        assert route_by_name("不存在") == "selection"  # fallback

    def test_get_en_to_cn(self):
        mapping = get_en_to_cn()
        assert mapping["selection"] == "单品选品分析"
        # image 不在此映射中（中文直接用作 mode）
        assert "image" not in mapping

    def test_get_mode_fallback(self):
        fb = get_mode_fallback()
        assert fb["selection"] == "单品选品分析"

    def test_get_all_names(self):
        names = get_all_names()
        assert len(names) == len(EXPECTED_INTENTS)
        assert names["selection"] == "单品选品分析"

    def test_get_complexity(self):
        assert get_complexity("selection") == Complexity.COMPLEX
        assert get_complexity("image") == Complexity.SIMPLE

    def test_get_decompose_rule(self):
        for mode in EXPECTED_INTENTS:
            rule = get_decompose_rule(mode)
            assert isinstance(rule, str) and len(rule) > 5, f"{mode} rule too short"

    def test_get_all_dags(self):
        dags = get_all_dags()
        assert len(dags) == len(EXPECTED_INTENTS)
        for dag in dags.values():
            assert "tasks" in dag
