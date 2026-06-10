"""测试 report.py — _clean 函数 + ReportBuilder"""
import json
import pytest
from backend.report import _clean


class TestCleanFunction:
    """_clean 清理函数"""

    def test_clean_json_no_wrapper(self, sample_json_str):
        """纯 JSON 不变"""
        result = _clean(sample_json_str)
        assert result.startswith("{")
        assert result.endswith("}")
        parsed = json.loads(result)
        assert parsed["title"] == "法式茶歇裙选品机会分析报告"

    def test_clean_json_with_markdown_fence(self, sample_json_str):
        """```json...``` 包裹 → 提取内部 JSON"""
        wrapped = f"```json\n{sample_json_str}\n```"
        result = _clean(wrapped)
        assert result.startswith("{")
        assert result.endswith("}")

    def test_clean_json_with_markdown_fence_no_lang(self, sample_json_str):
        """```...``` 包裹 → 提取内部 JSON"""
        wrapped = f"```\n{sample_json_str}\n```"
        result = _clean(wrapped)
        assert result.startswith("{")

    def test_clean_strips_leading_text(self, sample_json_str):
        """JSON 前的说明文字被移除"""
        wrapped = f"这是报告内容：\n{sample_json_str}"
        result = _clean(wrapped)
        assert result.startswith("{")

    def test_clean_strips_trailing_text(self, sample_json_str):
        """JSON 后的说明文字被移除"""
        wrapped = f"{sample_json_str}\n以上是完整JSON报告"
        result = _clean(wrapped)
        assert result.endswith("}")

    def test_clean_empty_string(self):
        """空字符串不崩溃"""
        result = _clean("")
        assert result == ""

    def test_clean_no_json(self):
        """无 JSON 内容不崩溃"""
        result = _clean("这是一段纯文本")
        assert isinstance(result, str)

    def test_clean_removes_html_wrapper(self):
        """HTML 包裹标签被移除"""
        wrapped = '<!DOCTYPE html><html><head></head><body>{"valid": true}</body></html>'
        result = _clean(wrapped)
        assert '"valid"}}' in result or result.strip() == '{"valid": true}'
