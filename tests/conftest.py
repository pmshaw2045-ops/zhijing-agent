
import sys
import os
import json
import pytest
from pathlib import Path

# 添加 backend 到 path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

# 强制使用测试 key（防止 config.py 加载 .env 时覆盖）
os.environ["DEEPSEEK_API_KEY"] = "test-key"
os.environ["ARK_API_KEY"] = "test-key"
os.environ["TAVILY_API_KEY"] = "test-key"
os.environ["BOCHA_API_KEY"] = "test-key"


@pytest.fixture
def integration():
    """集成测试标记：跳过无真实 API Key 的测试"""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key or key == "test-key":
        pytest.skip("跳过集成测试（需要设置 DEEPSEEK_API_KEY）")


@pytest.fixture
def sample_json_report():
    """返回一个标准 JSON 报告样本"""
    return json.dumps({
        "title": "法式茶歇裙选品机会分析报告",
        "sections": [
            {"type": "metrics", "data": {"items": [
                {"label": "搜索热度", "value": "82", "accent": "gold"}
            ]}},
            {"type": "bar_chart", "data": {"items": [
                {"label": "¥0-199", "value": 25, "color": "c1", "suffix": "%"}
            ]}},
            {"type": "swot", "data": {
                "brand": "a", "name": "法式茶歇裙",
                "s": ["款式经典"], "w": ["季节性"], "o": ["直播红利"], "t": ["价格战"]
            }},
            {"type": "insight", "data": {"style": "tip", "title": "结论", "body": "值得切入"}}
        ]
    })


@pytest.fixture
def sample_json_str(sample_json_report):
    """返回 JSON 字符串"""
    return sample_json_report
