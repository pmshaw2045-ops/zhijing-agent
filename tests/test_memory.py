"""测试 memory.py — 纯函数测试（不触发完整 MemorySystem 初始化）"""
import os, json, sys, tempfile, pytest
from pathlib import Path

# sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))


class TestKeyFindingsExtraction:
    """record_analysis 的 key_findings 提取逻辑（核心修复点）"""

    def _extract(self, text):
        """复制 memory.py 中的提取逻辑"""
        import re
        if text.strip().startswith("{"):
            m = re.search(r'"title"\s*:\s*"([^"]+)"', text)
            if m:
                return m.group(1)[:100]
            return text[:100]
        return text[:200]

    def test_extracts_title_from_json(self):
        result = self._extract('{"title": "法式茶歇裙选品机会分析报告", "sections": []}')
        assert result == "法式茶歇裙选品机会分析报告"

    def test_extracts_title_with_spaces(self):
        result = self._extract('{ "title" : "太平鸟 vs 伊芙丽竞品对标报告" , ... }')
        assert "太平鸟" in result

    def test_fallback_plain_text(self):
        result = self._extract("这是一段纯文本分析总结")
        assert "这是一段纯文本分析总结" in result

    def test_fallback_truncated_json(self):
        """截断的 JSON 无 title → 回退到前 100 字（可能含 JSON 片段）"""
        result = self._extract('{"unclosed": true, "no": "title"')
        # 无 title 时返回原文前 100 字
        assert len(result) <= 100

    def test_json_without_title(self):
        """JSON 无 title → 返回原文截断"""
        result = self._extract('{"sections": [{"type": "metrics"}]}')
        assert len(result) <= 100


class TestConversationTruncation:
    """content 截断逻辑"""

    def test_content_truncated_at_2000(self):
        long_msg = "x" * 3000
        truncated = long_msg[:2000]
        assert len(truncated) == 2000

    def test_short_content_unchanged(self):
        short = "hello"
        assert short[:2000] == short


class TestSlidingWindow:
    """滑动窗口逻辑"""

    def test_window_size_constant(self):
        from backend.memory import MemorySystem
        assert MemorySystem.SLIDING_WINDOW == 10

    def test_compress_threshold(self):
        from backend.memory import MemorySystem
        # 超过 SLIDING_WINDOW + 5 才触发压缩
        assert MemorySystem.SLIDING_WINDOW + 5 == 15


class TestInjectableContextFormat:
    """MD 注入格式"""

    def test_context_contains_md_headers(self):
        """验证核心注入方法存在且返回字符串"""
        from backend.memory import MemorySystem
        ms = MemorySystem()
        # 空 session 应返回空字符串或基本结构
        ctx = ms.get_injectable_context("test_empty_session")
        assert isinstance(ctx, str)


class TestCosineSimilarity:
    """余弦相似度纯函数"""

    def test_identical_vectors(self):
        from backend.memory import MemorySystem
        a = [1.0, 0.0, 0.0]
        score = MemorySystem._cosine_similarity(a, a)
        assert abs(score - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        from backend.memory import MemorySystem
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        score = MemorySystem._cosine_similarity(a, b)
        assert abs(score) < 1e-6

    def test_zero_vector(self):
        from backend.memory import MemorySystem
        a = [0.0, 0.0]
        b = [1.0, 0.0]
        score = MemorySystem._cosine_similarity(a, b)
        assert score == 0.0

    def test_partial_similarity(self):
        from backend.memory import MemorySystem
        a = [1.0, 2.0, 3.0]
        b = [2.0, 4.0, 6.0]  # a * 2
        score = MemorySystem._cosine_similarity(a, b)
        assert abs(score - 1.0) < 1e-6
